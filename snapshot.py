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
    """Try to resolve a needs_llm meeting deterministically: if any co-attendee
    is in learnings.patterns (single-bucket, unambiguous), use that bucket.

    Conservative — only resolves when there's a single unambiguous candidate.
    If multiple co-attendees resolve to different buckets, leave unresolved
    (the LLM step in /deploy-week will handle it).
    """
    co = m.get("co_attendees", [])
    patterns = learnings.get("patterns", {})
    candidates: set[tuple[str, ...]] = set()
    for email in co:
        if email in patterns:
            candidates.add(tuple(patterns[email]))
    if len(candidates) == 1:
        return list(next(iter(candidates)))
    return None


def all_resolved_meetings(prematch_data: dict, learnings: dict) -> tuple[list[dict], int]:
    """Returns (resolved_meetings, still_unresolved_count).

    Combines:
      - prematch_data['confident']['meetings'] (already have bucket_path)
      - prematch_data['needs_llm']['meetings'] that soft-resolve via co-attendees
    Excludes solo meetings (already filtered by prematch).
    """
    resolved: list[dict] = list(prematch_data["confident"]["meetings"])
    still_unresolved = 0
    for m in prematch_data["needs_llm"]["meetings"]:
        if m.get("solo"):
            continue
        bp = soft_resolve_meeting(m, learnings)
        if bp is None:
            still_unresolved += 1
            continue
        m2 = dict(m)
        m2["bucket_path"] = bp
        m2["reason"] = "soft_resolved_unambig_co_attendee"
        resolved.append(m2)
    return resolved, still_unresolved


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
    meetings, still_unresolved_meetings = all_resolved_meetings(prematch, learnings)

    by_window: dict[str, dict[str, float]] = {}
    for name, (ws, we) in wins.items():
        by_window[name] = per_path_minutes(all_sessions, meetings, ws, we)

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

    state = {
        "generated_at":         datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "windows_raw_minutes":  by_window,
        "total":                total_block,
        "engagements":          engagement_state,
        "live_bucket":          None,  # filled in by Phase 2 (live_bucket.py)
        "needs_llm": {
            "sessions": len(needs_llm_sessions),
            "meetings": still_unresolved_meetings,
        },
        "meeting_breakdown": {
            "total_resolved": len(meetings),
            "soft_resolved": sum(1 for m in meetings if m.get("reason") == "soft_resolved_unambig_co_attendee"),
            "still_unresolved": still_unresolved_meetings,
        },
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
