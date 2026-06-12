#!/usr/bin/env python3
"""snapshot.py — pulse widget state builder.

Runs the deploy-week pipeline (scan, fetch, prematch) for the widest window
(30d), then computes per-engagement even-split hours for today / 7d / 30d.
Compares against appetite.yaml caps and writes state.json atomically.

No LLM in the hot path. Pure subprocess + import.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

WIDGET_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(WIDGET_DIR))
import config  # noqa: E402
import scan_cowork  # noqa: E402

DEPLOY_WEEK = config.DEPLOY_WEEK          # only used for registry/learnings/rules DATA paths
SCRIPTS = WIDGET_DIR                       # vendored scan_sessions/prematch/fetch_meetings live here
APPETITE = WIDGET_DIR / "appetite.yaml"
STATE = WIDGET_DIR / "state.json"
UNCATEGORIZED = WIDGET_DIR / "uncategorized.json"
CACHE = WIDGET_DIR / ".cache"
CACHE.mkdir(exist_ok=True)

# Deterministic time math now comes from the timecore code-block (was deploy-week render).
sys.path.insert(0, str(config.TIMECORE_DIR))
from time_math import (  # noqa: E402
    compute_bucket_times,
    even_split_fractional,
    rollup_fractional,
)

LOCAL_TZ = config.LOCAL_TZ
GAP_MINUTES = 15   # tighter than /deploy-week's 30-min default — widget is a
                   # mid-week governor and needs to read honestly. 30 min counts
                   # "I opened a session at 9 and came back at 9:25" as 25 min
                   # of continuous activity. 15 min only counts real thinking
                   # pauses between turns, not coffee breaks.
WEEKS_PER_MONTH = 4.33


# --- windows ---------------------------------------------------------------

def week_start(now: datetime) -> datetime:
    """Most recent Monday 08:00 local that is <= now. Mon 7am rolls back to
    previous Monday 8am (last week's window). Aligns with /deploy-week boundary."""
    monday = now - timedelta(days=now.weekday())
    candidate = monday.replace(hour=8, minute=0, second=0, microsecond=0)
    if candidate > now:
        candidate -= timedelta(days=7)
    return candidate


def windows() -> dict[str, tuple[datetime, datetime]]:
    """today / wtd / 7d / 30d windows, tz-aware. wtd = Monday 8am → now."""
    now = datetime.now(LOCAL_TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "today": (today_start, now),
        "wtd":   (week_start(now), now),
        "7d":    (now - timedelta(days=7), now),
        "30d":   (now - timedelta(days=30), now),
    }


def iso_naive(dt: datetime) -> str:
    """scan_sessions.py compares against JSONL timestamps which are UTC stripped
    to naive. We must convert local→UTC first, then strip, or today's afternoon
    work falls outside the window (window_end in local time is hours behind
    JSONL ts in UTC)."""
    from datetime import timezone
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def iso_tz(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# --- pipeline (subprocess wrappers around deploy-week scripts) -------------

def run_scan(start: datetime, end: datetime) -> Path:
    out = CACHE / "sessions.json"
    subprocess.run(
        ["python3", str(SCRIPTS / "scan_sessions.py"),
         "--start", iso_naive(start),
         "--end",   iso_naive(end),
         "--out",   str(out)],
        check=True, capture_output=True,
    )
    return out


def run_fetch_meetings(start: datetime, end: datetime) -> Path:
    """OAuth can fail — return an empty meetings file in that case so the
    rest of the pipeline still runs. Meetings are not currently used by the
    widget's appetite math (sessions only); this is wired up for future use."""
    out = CACHE / "meetings.json"
    try:
        subprocess.run(
            ["python3", str(SCRIPTS / "fetch_meetings.py"),
             "--start", iso_tz(start),
             "--end",   iso_tz(end),
             "--out",   str(out)],
            check=True, capture_output=True, timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        with open(out, "w") as f:
            json.dump({"stats": {"meetings": 0, "error": "fetch_failed"}, "meetings": []}, f)
    return out


def run_prematch(sessions_path: Path, meetings_path: Path) -> dict:
    out = CACHE / "prematch.json"
    subprocess.run(
        ["python3", str(SCRIPTS / "prematch.py"),
         "--sessions",  str(sessions_path),
         "--meetings",  str(meetings_path),
         "--registry",  str(DEPLOY_WEEK / "context" / "bucket-registry.yaml"),
         "--learnings", str(DEPLOY_WEEK / "context" / "learnings.yaml"),
         "--rules",     str(DEPLOY_WEEK / "context" / "disambiguation-rules.yaml"),
         "--out",       str(out)],
        check=True, capture_output=True,
    )
    with open(out) as f:
        return json.load(f)


# --- meeting resolution ----------------------------------------------------

def soft_resolve_meeting(m: dict, learnings: dict) -> list[str] | None:
    """Resolve a needs_llm meeting deterministically using everything the registry
    already knows, in priority order:

      1. title_rules   — a curated keyword in the title wins outright
                         (e.g. 'Podcast Recording' -> [SC, Redacted]).
      2. patterns      — an exact co-attendee email -> bucket.
      3. domain_patterns — a co-attendee's email domain -> bucket (fallback).
      4. tie-break     — if candidates are nested (one extends the others), the
                         deepest path wins (e.g. [SC,GI] vs [SC,GI,Lee] -> Lee).

    Still conservative: genuinely conflicting candidates (not nested) stay
    unresolved, so the user (or /deploy-week's LLM) decides.
    """
    title = (m.get("title") or "").lower()
    for kw, bucket in (learnings.get("title_rules") or {}).items():
        if str(kw).lower() in title:
            return list(bucket)

    co = m.get("co_attendees", [])
    patterns = learnings.get("patterns", {})
    domains = learnings.get("domain_patterns", {})
    multi = learnings.get("multi_bucket_attendees", {})
    candidates: set[tuple[str, ...]] = set()
    for email in co:
        if email in multi:
            continue  # explicitly ambiguous (resolved by title rules, not their vote)
        if email in patterns:
            candidates.add(tuple(patterns[email]))
        else:
            dom = email.split("@")[-1].lower()
            if dom in domains:
                candidates.add(tuple(domains[dom]))

    if len(candidates) == 1:
        return list(next(iter(candidates)))
    if len(candidates) > 1:
        # nested tie-break: pick the deepest path iff every other candidate is a
        # prefix of it (same engagement, more specific). Otherwise truly ambiguous.
        longest = max(candidates, key=len)
        if all(longest[:len(c)] == c for c in candidates):
            return list(longest)
    return None


def all_resolved_meetings(prematch_data: dict, learnings: dict) -> tuple[list[dict], list[dict]]:
    """Returns (resolved_meetings, unresolved_meetings).

    Combines:
      - prematch_data['confident']['meetings'] (already have bucket_path)
      - prematch_data['needs_llm']['meetings'] that soft-resolve via co-attendees
    Excludes solo meetings (already filtered by prematch). Unresolved meetings
    (real, co-attended, but unmatched) are returned so they can be surfaced for
    the user to resolve.
    """
    resolved: list[dict] = list(prematch_data["confident"]["meetings"])
    unresolved: list[dict] = []
    for m in prematch_data["needs_llm"]["meetings"]:
        if m.get("solo"):
            continue
        bp = soft_resolve_meeting(m, learnings)
        if bp is None:
            unresolved.append(m)
            continue
        m2 = dict(m)
        m2["bucket_path"] = bp
        m2["reason"] = "soft_resolved_unambig_co_attendee"
        resolved.append(m2)
    return resolved, unresolved


# --- per-window math -------------------------------------------------------

def _meeting_intervals_per_bucket(
    meetings: list[dict],
    start: datetime,
    end: datetime,
    local_tz: ZoneInfo,
) -> dict[tuple, list[tuple[datetime, datetime]]]:
    """Returns {bucket_path_tuple: [(clipped_start, clipped_end), ...]}.

    Normalizes naive datetimes (all-day events) to local_tz and clips to the
    window. Returns intervals (not scalars) so they can participate in the
    same sweep-line as session intervals.
    """
    out: dict[tuple, list[tuple[datetime, datetime]]] = {}
    for m in meetings:
        try:
            m_start = datetime.fromisoformat(m["start"])
            m_end = datetime.fromisoformat(m["end"])
        except (KeyError, ValueError):
            continue
        if m_start.tzinfo is None:
            m_start = m_start.replace(tzinfo=local_tz)
        else:
            m_start = m_start.astimezone(local_tz)
        if m_end.tzinfo is None:
            m_end = m_end.replace(tzinfo=local_tz)
        else:
            m_end = m_end.astimezone(local_tz)
        s = max(m_start, start)
        e = min(m_end, end)
        if e <= s:
            continue
        bp = tuple(m["bucket_path"])
        out.setdefault(bp, []).append((s, e))
    return out


def _compose_per_path_minutes(
    per_bucket_sessions: dict,
    meetings: list[dict],
    start: datetime,
    end: datetime,
    local_tz: ZoneInfo,
) -> dict[str, float]:
    """Pure-function composition of session intervals + meetings → per-path minutes.

    Meetings enter the same per-bucket sweep-line as sessions. Intra-bucket
    merge swallows session-during-same-bucket-meeting overlap; cross-bucket
    concurrency is even-split. Wall-clock faithful: no minute counted twice.
    """
    per_bucket = {bp: list(ivs) for bp, ivs in per_bucket_sessions.items()}
    for bp, ivs in _meeting_intervals_per_bucket(meetings, start, end, local_tz).items():
        per_bucket.setdefault(bp, []).extend(ivs)
    leaf_frac = even_split_fractional(per_bucket)
    rolled = rollup_fractional(leaf_frac)
    return {".".join(bp): mins for bp, mins in rolled.items()}


def per_path_minutes(
    sessions: list[dict],
    meetings: list[dict],
    start: datetime,
    end: datetime,
) -> dict[str, float]:
    """Returns {dotted_bucket_path: minutes} for the window."""
    per_bucket, _ = compute_bucket_times(sessions, start, end, GAP_MINUTES, LOCAL_TZ)
    return _compose_per_path_minutes(per_bucket, meetings, start, end, LOCAL_TZ)


def meeting_path_minutes(
    meetings: list[dict],
    start: datetime,
    end: datetime,
) -> dict[str, float]:
    """Returns {dotted_bucket_path: minutes} counting ONLY meetings in the window.
    Same even-split + rollup as the combined calc, so the breakout is consistent."""
    per_bucket = _meeting_intervals_per_bucket(meetings, start, end, LOCAL_TZ)
    leaf_frac = even_split_fractional(per_bucket)
    rolled = rollup_fractional(leaf_frac)
    return {".".join(bp): mins for bp, mins in rolled.items()}


def meetings_in_window(meetings: list[dict], start: datetime, end: datetime) -> int:
    """Count resolved meetings whose start falls in [start, end)."""
    n = 0
    for m in meetings:
        try:
            s = datetime.fromisoformat(m["start"])
        except (KeyError, ValueError):
            continue
        s = s.replace(tzinfo=LOCAL_TZ) if s.tzinfo is None else s.astimezone(LOCAL_TZ)
        if start <= s < end:
            n += 1
    return n


def build_people(learnings: dict) -> list[dict]:
    """Surface the learned co-attendee map: person -> project. Display name is
    derived from the email local-part (the registry keys on email). Self-emails
    (you) are skipped — you are not a 'person who maps to a project'."""
    self_emails = set(config.CALENDAR_SELF_EMAILS)
    out = []
    for email, bucket in (learnings.get("patterns") or {}).items():
        if email in self_emails:
            continue
        local = str(email).split("@")[0]
        name = local.replace(".", " ").replace("_", " ").title()
        leaf = bucket[-1] if isinstance(bucket, list) and bucket else str(bucket)
        out.append({"name": name, "project": leaf})
    out.sort(key=lambda p: (p["project"], p["name"]))
    return out


def _decode_project(encoded: str | None) -> str:
    """~/.claude/projects encodes a path as the abs path with '/' -> '-'. Decode
    to a readable path for the user/Claude (best-effort; dashes in dir names are
    rare and harmless here)."""
    if not encoded:
        return ""
    return encoded.replace("-", "/")


def _session_brief(s: dict) -> dict:
    edits = s.get("edit_paths") or {}
    top = sorted(edits.items(), key=lambda kv: -kv[1])[:5] if isinstance(edits, dict) else []
    return {
        "project_dir": _decode_project(s.get("encoded")),
        "top_files": [p for p, _ in top],
        "first_message": (s.get("first_msg") or "")[:200],
        "reason": s.get("reason"),
    }


def _meeting_brief(m: dict) -> dict:
    return {
        "title": m.get("title"),
        "attendees": m.get("co_attendees", []),
        "start": m.get("start"),
    }


def write_uncategorized(sessions: list[dict], meetings: list[dict],
                        generated_at: str) -> None:
    """Dump the unresolved work so `setup/RESOLVE.md` (run in Claude Code) can
    categorize it and teach the registry. Local file, gitignored."""
    payload = {
        "generated_at": generated_at,
        "note": "Pulse could not confidently categorize these. "
                "Run: 'Read setup/RESOLVE.md and resolve my uncategorized Pulse items.'",
        "sessions": [_session_brief(s) for s in sessions],
        "meetings": [_meeting_brief(m) for m in meetings],
    }
    tmp = UNCATEGORIZED.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    tmp.rename(UNCATEGORIZED)


def uncategorized_detail(sessions: list[dict], meetings: list[dict]) -> dict:
    """A short preview for the panel's Resolve view (labels only, capped)."""
    def slabel(s: dict) -> str:
        edits = s.get("edit_paths") or {}
        if isinstance(edits, dict) and edits:
            top = sorted(edits.items(), key=lambda kv: -kv[1])[0][0]
            return top.split("/")[-1] or top
        fm = (s.get("first_msg") or "").strip()
        if fm.startswith("<"):                 # drop a leading system/command tag
            j = fm.find(">")
            fm = fm[j + 1:].strip() if j != -1 else fm
        if fm.lower().startswith("caveat"):    # system command-expansion preamble, no signal
            fm = ""
        if fm:
            snip = " ".join(fm.split()[:5])
            return (snip[:34] + "…") if len(snip) > 34 else snip
        return "(uncategorized session)"
    return {
        "sessions": [slabel(s) for s in sessions][:6],
        "meetings": [m.get("title") or "(untitled)" for m in meetings][:6],
    }


def find_hours(rolled: dict[str, float], leaf_name: str) -> float:
    """Match by last path segment so a leaf name finds its full dotted path (e.g. 'Alpha' -> 'Acme.Alpha')."""
    for path_str, mins in rolled.items():
        if path_str.split(".")[-1] == leaf_name:
            return mins / 60.0
    return 0.0


# --- appetite --------------------------------------------------------------

def load_appetite() -> dict[str, dict]:
    if not APPETITE.exists():
        return {}
    with open(APPETITE) as f:
        data = yaml.safe_load(f) or {}
    return data.get("engagements", {})


def load_total_budget() -> dict | None:
    """Top-level billable-hours budget (weekly + monthly). Returns None if not set."""
    if not APPETITE.exists():
        return None
    with open(APPETITE) as f:
        data = yaml.safe_load(f) or {}
    tb = data.get("total_budget")
    if not tb:
        return None
    return {
        "weekly_hours":  float(tb.get("weekly_hours",  0)),
        "monthly_hours": float(tb.get("monthly_hours", 0)),
    }


def caps(monthly_value: float, target_rate: float) -> tuple[float, float]:
    monthly_cap = monthly_value / target_rate
    weekly_cap = monthly_cap / WEEKS_PER_MONTH
    return weekly_cap, monthly_cap


def remaining_or_over(actual_h: float, cap_h: float) -> dict:
    delta = cap_h - actual_h
    if delta >= 0:
        return {"hours_left": round(delta, 1), "over": False}
    return {"hours_over": round(-delta, 1), "over": True}


# --- main ------------------------------------------------------------------

def main() -> None:
    wins = windows()
    widest_start, widest_end = wins["30d"]

    sess_path = run_scan(widest_start, widest_end)
    meet_path = run_fetch_meetings(widest_start, widest_end)
    prematch = run_prematch(sess_path, meet_path)

    confident_sessions = prematch["confident"]["sessions"]
    needs_llm_sessions = prematch["needs_llm"]["sessions"]

    # Cowork sessions live outside ~/.claude/projects/. The scanner normalizes
    # them into the CLI session shape and pre-classifies via slash command /
    # title regex / email default, so they slot straight into per_path_minutes
    # alongside CLI sessions — cross-surface even-split-fractional dedupe
    # happens for free.
    cowork_sessions = scan_cowork.scan(widest_start, widest_end)
    all_sessions = confident_sessions + cowork_sessions

    # Load learnings for soft meeting resolution
    with open(DEPLOY_WEEK / "context" / "learnings.yaml") as f:
        learnings = yaml.safe_load(f) or {}
    meetings, unresolved_meetings = all_resolved_meetings(prematch, learnings)
    still_unresolved_meetings = len(unresolved_meetings)

    by_window: dict[str, dict[str, float]] = {}
    for name, (ws, we) in wins.items():
        by_window[name] = per_path_minutes(all_sessions, meetings, ws, we)

    # Meeting-only minutes for the week, so the panel can break out meetings vs sessions.
    meeting_wtd = meeting_path_minutes(meetings, *wins["wtd"])

    appetite = load_appetite()
    engagement_state: dict[str, dict] = {}
    for name, cfg in appetite.items():
        weekly_cap, monthly_cap = caps(cfg["monthly_value"], cfg["target_rate"])
        h_today = find_hours(by_window["today"], name)
        h_wtd   = find_hours(by_window["wtd"],   name)
        h_7d    = find_hours(by_window["7d"],    name)
        h_30d   = find_hours(by_window["30d"],   name)
        engagement_state[name] = {
            "monthly_value":  cfg["monthly_value"],
            "target_rate":    cfg["target_rate"],
            "weekly_cap_h":   round(weekly_cap,  2),
            "monthly_cap_h":  round(monthly_cap, 2),
            "today_h":        round(h_today, 2),
            "meeting_h":      round(find_hours(meeting_wtd, name), 2),
            "wtd": {"actual_h": round(h_wtd, 2), **remaining_or_over(h_wtd, weekly_cap)},
            "7d":  {"actual_h": round(h_7d,  2), **remaining_or_over(h_7d,  weekly_cap)},
            "30d": {"actual_h": round(h_30d, 2), **remaining_or_over(h_30d, monthly_cap)},
        }

    # Total billable: sum the appetite engagements (NOT every bucket).
    total_block: dict | None = None
    total_budget = load_total_budget()
    if total_budget:
        sum_today = sum(s["today_h"]      for s in engagement_state.values())
        sum_wtd   = sum(s["wtd"]["actual_h"] for s in engagement_state.values())
        sum_7d    = sum(s["7d"]["actual_h"]  for s in engagement_state.values())
        sum_30d   = sum(s["30d"]["actual_h"] for s in engagement_state.values())
        total_block = {
            "weekly_cap_h":  total_budget["weekly_hours"],
            "monthly_cap_h": total_budget["monthly_hours"],
            "today_h":  round(sum_today, 2),
            "wtd": {"actual_h": round(sum_wtd, 2), **remaining_or_over(sum_wtd, total_budget["weekly_hours"])},
            "7d":  {"actual_h": round(sum_7d,  2), **remaining_or_over(sum_7d,  total_budget["weekly_hours"])},
            "30d": {"actual_h": round(sum_30d, 2), **remaining_or_over(sum_30d, total_budget["monthly_hours"])},
        }

    log_path = DEPLOY_WEEK / "data" / "session-log.md"
    last_dw = (
        datetime.fromtimestamp(log_path.stat().st_mtime, tz=LOCAL_TZ).isoformat(timespec="seconds")
        if log_path.exists() else None
    )

    generated_at = datetime.now(LOCAL_TZ).isoformat(timespec="seconds")
    # Dump the unresolved work for setup/RESOLVE.md (run in Claude Code) to act on.
    write_uncategorized(needs_llm_sessions, unresolved_meetings, generated_at)

    state = {
        "generated_at":         generated_at,
        "repo_path":            str(WIDGET_DIR),
        "windows_raw_minutes":  by_window,
        "total":                total_block,
        "engagements":          engagement_state,
        "live_bucket":          None,  # filled in by Phase 2 (live_bucket.py)
        "needs_llm": {
            "sessions": len(needs_llm_sessions),
            "meetings": still_unresolved_meetings,
        },
        "uncategorized_detail": uncategorized_detail(needs_llm_sessions, unresolved_meetings),
        "meeting_breakdown": {
            "total_resolved": len(meetings),
            "soft_resolved": sum(1 for m in meetings if m.get("reason") == "soft_resolved_unambig_co_attendee"),
            "still_unresolved": still_unresolved_meetings,
        },
        "meetings_wtd": meetings_in_window(meetings, *wins["wtd"]),
        "people": build_people(learnings),
        "last_deploy_week_run": last_dw,
    }

    # Atomic write
    tmp = STATE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, default=str)
    tmp.rename(STATE)

    # Human summary
    print(f"wrote {STATE}")
    print(f"sessions: {len(confident_sessions)} confident, {len(needs_llm_sessions)} needs_llm")
    for name, st in engagement_state.items():
        wtd = st["wtd"]
        status = f"OVER {wtd['hours_over']}h" if wtd["over"] else f"{wtd['hours_left']}h left"
        print(f"  {name:8} wtd {st['wtd']['actual_h']:5.1f}/{st['weekly_cap_h']:>4.1f}h  {status}")


if __name__ == "__main__":
    main()
