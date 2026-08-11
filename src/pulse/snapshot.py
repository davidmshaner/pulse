#!/usr/bin/env python3
"""snapshot.py — pulse widget state builder.

Runs the vendored pipeline (scan, fetch, prematch) for the widest window
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

PKG_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PKG_DIR))
import config  # noqa: E402
import prematch  # noqa: E402 — session_key: the override-key contract (#64)
import scan_codex  # noqa: E402
import scan_cowork  # noqa: E402
import updatecheck  # noqa: E402

SCRIPTS = config.PKG_DIR                   # vendored scan_sessions/prematch/fetch_meetings live here
APPETITE = config.DATA_DIR / "appetite.yaml"
STATE = config.DATA_DIR / "state.json"
UNCATEGORIZED = config.DATA_DIR / "uncategorized.json"
CACHE = config.DATA_DIR / ".cache"
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


def month_start(now: datetime) -> datetime:
    """First of the current month at 00:00 local. The income meter (#38) bills by
    calendar month-to-date — resets on the 1st, matching monthly invoicing — NOT a
    rolling 30d window (which never resets and drifts against a monthly cap)."""
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def windows() -> dict[str, tuple[datetime, datetime]]:
    """today / wtd / mtd / 7d / 30d windows, tz-aware. wtd = Monday 8am → now;
    mtd = 1st of month 00:00 → now (income meter, #38)."""
    now = datetime.now(LOCAL_TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "today": (today_start, now),
        "wtd":   (week_start(now), now),
        "mtd":   (month_start(now), now),
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


# --- pipeline (subprocess wrappers around the vendored src/pulse scripts) ---

def run_scan(start: datetime, end: datetime) -> Path:
    out = CACHE / "sessions.json"
    subprocess.run(
        [sys.executable, str(SCRIPTS / "scan_sessions.py"),
         "--start", iso_naive(start),
         "--end",   iso_naive(end),
         "--out",   str(out)],
        check=True, capture_output=True,
    )
    return out


def run_fetch_meetings(start: datetime, end: datetime) -> Path:
    """OAuth can fail — return an empty meetings file in that case so the
    rest of the pipeline still runs. Resolved meetings ARE folded into the
    appetite math: per_path_minutes() composes them into the same per-bucket
    sweep-line as sessions, so they count toward the hour bars and caps. Only
    meetings that resolve to a bucket count; unresolved ones stay uncategorized."""
    out = CACHE / "meetings.json"
    try:
        subprocess.run(
            [sys.executable, str(SCRIPTS / "fetch_meetings.py"),
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
    try:
        subprocess.run(
            [sys.executable, str(SCRIPTS / "prematch.py"),
             "--sessions",  str(sessions_path),
             "--meetings",  str(meetings_path),
             "--registry",  str(config.REGISTRY),
             "--learnings", str(config.LEARNINGS),
             "--rules",     str(config.RULES),
             "--overrides", str(config.OVERRIDES),
             "--out",       str(out)],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        # prematch now reads hand-edited input (session-overrides.yaml); a
        # swallowed stderr would leave the user with a dead snapshot and no
        # pointer to the file they just broke.
        stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        raise RuntimeError(f"prematch failed (exit {e.returncode}):\n{stderr[-2000:]}") from e
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
        # The override key for setup/RESOLVE.md's session-overrides.yaml (#64).
        "session_file": prematch.session_key(s),
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


def is_overhead_session(s: dict) -> bool:
    """A needs_llm session with no file edits has no 'where work landed' signal,
    and its directory didn't resolve to a project either — unattributable overhead
    (exploration, Q&A like 'do I have tokens?'), not billable to any one project.
    These are reported separately, never dumped into the resolve queue."""
    edits = s.get("edit_paths") or {}
    return not (isinstance(edits, dict) and edits)


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


def _read_prior_update_check() -> dict | None:
    """The last update_check block from state.json, so run_check can throttle its GitHub
    request and carry the last-known remote sha forward when offline. Best-effort."""
    try:
        with open(STATE) as f:
            return (json.load(f) or {}).get("update_check")
    except (OSError, json.JSONDecodeError):
        return None


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


def load_groups() -> list[dict]:
    """User-defined roll-up groups. Each group bundles member engagements under
    one aggregate cap. Returns a list of {name, members, weekly_hours, monthly_hours}
    in definition order.

    Back-compat: if `groups:` is absent but the legacy `total_budget:` is present,
    synthesize a single 'Billable' group over all members ('*'), so old configs and
    examples/appetite.example.yaml keep working with no edit.
    """
    if not APPETITE.exists():
        return []
    with open(APPETITE) as f:
        data = yaml.safe_load(f) or {}
    groups = data.get("groups")
    if groups:
        return [{"name": name, **(g or {})} for name, g in groups.items()]
    tb = data.get("total_budget")
    if tb:
        return [{
            "name": "Billable",
            "members": "*",
            "weekly_hours":  float(tb.get("weekly_hours",  0)),
            "monthly_hours": float(tb.get("monthly_hours", 0)),
        }]
    return []


def caps(monthly_value: float, target_rate: float) -> tuple[float, float]:
    monthly_cap = monthly_value / target_rate
    weekly_cap = monthly_cap / WEEKS_PER_MONTH
    return weekly_cap, monthly_cap


def engagement_caps(cfg: dict) -> tuple[float | None, float | None]:
    """Resolve (weekly_cap_h, monthly_cap_h) for one engagement. Three modes:

      rate   — monthly_value + target_rate  -> derived caps (David's billable style)
      hours  — weekly_hours and/or monthly_hours -> direct caps (the missing one is
               derived via WEEKS_PER_MONTH)
      track  — neither  -> (None, None): tracked, shown, but uncapped (no bar). This
               is how Personal / Shaner Consulting / Redacted / Pipeline come in.
    """
    if "monthly_value" in cfg and "target_rate" in cfg:
        return caps(cfg["monthly_value"], cfg["target_rate"])
    if "weekly_hours" in cfg or "monthly_hours" in cfg:
        wk = cfg.get("weekly_hours")
        mo = cfg.get("monthly_hours")
        wk = float(wk) if wk is not None else (float(mo) / WEEKS_PER_MONTH if mo is not None else None)
        mo = float(mo) if mo is not None else (wk * WEEKS_PER_MONTH if wk is not None else None)
        return wk, mo
    return None, None


def remaining_or_over(actual_h: float, cap_h: float) -> dict:
    delta = cap_h - actual_h
    if delta >= 0:
        return {"hours_left": round(delta, 1), "over": False}
    return {"hours_over": round(-delta, 1), "over": True}


# --- income-meter mode (#38) -----------------------------------------------
# The inverse of rate-mode: instead of dividing a dollar value into an hour cap,
# income mode meters cumulative $ billed for the calendar month ($ = MTD hours ×
# bill_rate), with an optional dollar ceiling. `bill_rate` selects it.

def is_income_mode(cfg: dict) -> bool:
    """True when this engagement meters dollars (has an explicit bill_rate), rather
    than resolving to an hour cap. Income engagements are handled separately in
    main() and never pass through engagement_caps."""
    return "bill_rate" in cfg


def income_billed(actual_h: float, bill_rate: float) -> float:
    """Dollars billed = hours worked × $/hr. The running-meter value."""
    return actual_h * bill_rate


def dollars_remaining_or_over(billed: float, cap_value: float) -> dict:
    """The $ analog of remaining_or_over: $ left under a monthly ceiling, or $ over
    it. Rounded to whole dollars (the card shows e.g. '$1,750 left' / 'OVER $1,000')."""
    delta = cap_value - billed
    if delta >= 0:
        return {"dollars_left": round(delta), "over": False}
    return {"dollars_over": round(-delta), "over": True}


def appetite_errors(appetite: dict[str, dict], groups=None,
                    registry_buckets=None) -> list[str]:
    """Config errors that MUST halt the snapshot rather than silently mismeter.

    Engagement-mode (#38): income-mode (`bill_rate`) and the hour-cap vocabularies
    (`monthly_value`/`target_rate` rate-mode, or `weekly_hours`/`monthly_hours`
    hours-mode) compute in opposite directions, so an engagement declaring both is
    ambiguous — reject it. `monthly_cap_value` without `bill_rate` is rejected too
    (a dollar ceiling with no rate can't be metered).

    Nested groups (#31): when `groups` (a {name: members} map) is given, reject an
    unknown member, a membership cycle, and any rollup that would double-count an
    engagement (reachable via a group and that group's ancestor, or via two
    sub-groups). When `registry_buckets` is given, reject a `children:` bucket whose
    source_path is not under its parent's. Both default off, so existing single-arg
    callers are unaffected."""
    hour_cap_keys = ("monthly_value", "target_rate", "weekly_hours", "monthly_hours")
    errs: list[str] = []
    for name, cfg in appetite.items():
        cfg = cfg or {}
        if is_income_mode(cfg):
            clash = [k for k in hour_cap_keys if k in cfg]
            if clash:
                errs.append(
                    f"engagement '{name}' mixes income-mode (bill_rate) with hour-cap "
                    f"keys ({', '.join(clash)}) — pick one: bill_rate for a $ meter, or "
                    f"monthly_value+target_rate / weekly_hours for an hour cap."
                )
        elif "monthly_cap_value" in cfg:
            errs.append(
                f"engagement '{name}' sets monthly_cap_value without bill_rate — a $ "
                f"ceiling needs a bill_rate ($/hr) to meter against."
            )
    if groups is not None:
        for c in sorted(set(groups) & set(appetite.keys())):
            errs.append(
                f"'{c}' is defined as BOTH an engagement and a group — a member "
                f"reference to it would be ambiguous; rename one of them."
            )
        errs += _group_member_errors(groups, appetite.keys())
        cycles = _group_cycle_errors(groups)
        errs += cycles
        if not cycles:      # the double-count walk assumes no cycle (else it can't terminate)
            errs += _group_double_count_errors(groups, appetite.keys())
    if registry_buckets is not None:
        errs += registry_child_path_errors(registry_buckets)
    return errs


def _full_path_for(rolled: dict[str, float], leaf: str) -> str | None:
    """The full dotted path in `rolled` whose last segment is `leaf` (or None)."""
    for path_str in rolled:
        if path_str.split(".")[-1] == leaf:
            return path_str
    return None


def apply_remainder(engagement_state: dict, canon: dict[str, str | None],
                    remainder_names: list[str]) -> None:
    """Mutate each remainder engagement so its hours = parent total MINUS the sum of
    every other engagement that is a strict descendant of it. This is how 'Shaner
    Consulting' (bucket SC) becomes 'all SC work that isn't a billable client or
    Redacted/Pipeline' — it absorbs SC-internal AND bare-SC-root sessions without
    double-counting the billable children. `canon` maps engagement -> canonical
    dotted path (from the widest window)."""
    for name in remainder_names:
        parent = canon.get(name)
        if not parent:
            continue
        desc = [m for m in engagement_state
                if m != name and canon.get(m) and canon[m].startswith(parent + ".")]
        st = engagement_state[name]
        st["today_h"] = round(max(0.0, st["today_h"]
                                  - sum(engagement_state[m]["today_h"] for m in desc)), 2)
        for wk in ("wtd", "7d", "30d"):
            sub = sum(engagement_state[m][wk]["actual_h"] for m in desc)
            st[wk]["actual_h"] = round(max(0.0, st[wk]["actual_h"] - sub), 2)
        st["remainder"] = True
        st["remainder_minus"] = desc


def _group_overlap(members: list[str], engagement_state: dict, rolled: dict[str, float]) -> list[str]:
    """Warn if two members' bucket paths are in an ancestor relationship — summing
    them double-counts (e.g. an 'SC' parent member alongside its 'SC.Metis' child).
    Remainder engagements are exempt (the parent-minus-children subtraction is
    intentional and already deduped). Uses resolved 30d paths. Never raises."""
    paths: dict[str, str] = {}
    for m in members:
        if engagement_state[m].get("remainder"):
            continue
        p = _full_path_for(rolled, engagement_state[m]["bucket"])
        if p:
            paths[m] = p
    warnings: list[str] = []
    items = list(paths.items())
    for ma, pa in items:
        for mb, pb in items:
            if ma != mb and pb.startswith(pa + "."):
                warnings.append(f"{ma} ({pa}) contains {mb} ({pb}) — sum double-counts")
    return warnings


# --- nested groups (#31) ---------------------------------------------------
# A group's `members` may name OTHER groups as well as engagements (recursive,
# no new field). These pure helpers resolve a group to its transitive engagement
# set, order the group forest for indented rendering, and build one group block.

def _is_wildcard(members) -> bool:
    return members in ("*", ["*"])


def resolve_group_engagements(name, groups_by_name, engagement_names, seen=None):
    """The ordered, de-duplicated list of engagements a group transitively contains.

    `groups_by_name` maps group name -> its `members` list (each member is an
    engagement name or another group name). A member that is a group expands to
    that group's engagements (recursively, in file order); a member that is an
    engagement is included directly; anything else is skipped. An engagement
    reachable via more than one path is counted ONCE — the summed rollup must
    never double-count. `seen` guards against membership cycles (a config error
    caught by validation) so resolution always terminates."""
    seen = seen or set()
    if name in seen:
        return []
    seen = seen | {name}
    members = groups_by_name.get(name)
    if _is_wildcard(members):
        return list(engagement_names)
    eng_set = set(engagement_names)
    out: list[str] = []
    for m in (members or []):
        if m in groups_by_name:
            out.extend(resolve_group_engagements(m, groups_by_name, engagement_names, seen))
        elif m in eng_set:
            out.append(m)
    return list(dict.fromkeys(out))            # dedupe, preserve first occurrence


def group_tree_order(groups):
    """DFS pre-order of the group forest as (name, depth) pairs, driving indented
    rendering. A group named as a member by another group is rendered only under
    its parent (indented), never also at top level; roots are groups referenced by
    no other group, kept in definition order. Cycle-safe. For a FLAT config (no
    group names another group) every group is a depth-0 root in definition order —
    identical to the pre-nesting layout."""
    groups_by_name = {g["name"]: (g.get("members") or []) for g in groups}
    referenced = set()
    for g in groups:
        members = g.get("members")
        if _is_wildcard(members):
            continue
        for m in (members or []):
            if m in groups_by_name:
                referenced.add(m)
    ordered: list[tuple[str, int]] = []

    def visit(name, depth, seen):
        if name in seen:
            return
        seen = seen | {name}
        ordered.append((name, depth))
        members = groups_by_name.get(name)
        if _is_wildcard(members):
            return
        for m in (members or []):
            if m in groups_by_name:
                visit(m, depth + 1, seen)

    for g in groups:
        if g["name"] not in referenced:
            visit(g["name"], 0, set())
    return ordered


def direct_engagement_members(members, engagement_names):
    """A group's DIRECT member names that are engagements, in config order (#66).
    Distinct from `resolve_group_engagements` (the recursive leaf expansion used
    for cap math): sub-group members are excluded — their engagements render
    under the sub-group, not the parent. '*' = every defined engagement."""
    if _is_wildcard(members):
        return list(engagement_names)
    return [m for m in (members or []) if m in engagement_names]


def build_group_block(name, present, engagement_state, weekly_cap_h,
                      monthly_cap_h, depth=0):
    """One group's state block: its members' summed hours per window, its caps
    (or None -> a capless roll-up that renders track-style), and its nesting
    depth. `present` is the resolved, de-duplicated engagement list, so the sum
    counts each leaf once. Cap math mirrors the flat-group path exactly, so a
    depth-0 capped group is byte-identical to before nested groups existed."""
    sum_today = sum(engagement_state[m]["today_h"]         for m in present)
    sum_wtd   = sum(engagement_state[m]["wtd"]["actual_h"]  for m in present)
    sum_7d    = sum(engagement_state[m]["7d"]["actual_h"]   for m in present)
    sum_30d   = sum(engagement_state[m]["30d"]["actual_h"]  for m in present)
    capless = not weekly_cap_h and not monthly_cap_h
    block: dict = {
        "name":          name,
        "members":       present,
        "depth":         depth,
        "weekly_cap_h":  None if capless else float(weekly_cap_h or 0),
        "monthly_cap_h": None if capless else float(monthly_cap_h or 0),
        "today_h":       round(sum_today, 2),
    }
    if capless:
        # No cap -> a pure roll-up: hours only, no bar, no over/left verdict.
        block["track_only"] = True
        block["wtd"] = {"actual_h": round(sum_wtd, 2)}
        block["7d"]  = {"actual_h": round(sum_7d,  2)}
        block["30d"] = {"actual_h": round(sum_30d, 2)}
    else:
        wk = float(weekly_cap_h or 0)
        mo = float(monthly_cap_h or 0)
        block["wtd"] = {"actual_h": round(sum_wtd, 2), **remaining_or_over(sum_wtd, wk)}
        block["7d"]  = {"actual_h": round(sum_7d,  2), **remaining_or_over(sum_7d,  wk)}
        block["30d"] = {"actual_h": round(sum_30d, 2), **remaining_or_over(sum_30d, mo)}
    return block


def _group_member_errors(groups_by_name, engagement_names) -> list[str]:
    """A group member must name a defined engagement or another defined group."""
    eng = set(engagement_names)
    gnames = set(groups_by_name)
    errs: list[str] = []
    for name, members in groups_by_name.items():
        if _is_wildcard(members):
            continue
        for m in (members or []):
            if m not in eng and m not in gnames:
                errs.append(
                    f"group '{name}' has unknown member '{m}' — not a defined "
                    f"engagement or group."
                )
    return errs


def _group_cycle_errors(groups_by_name) -> list[str]:
    """A group must not (transitively) contain itself — a membership cycle would
    make its rollup ill-defined. Reports each distinct cycle once."""
    errs: list[str] = []
    seen_cycles: set[frozenset] = set()

    def dfs(name, stack):
        if name in stack:
            cyc = stack[stack.index(name):] + [name]
            key = frozenset(cyc)
            if key not in seen_cycles:
                seen_cycles.add(key)
                errs.append(f"group membership cycle: {' -> '.join(cyc)}")
            return
        members = groups_by_name.get(name)
        if _is_wildcard(members):
            return
        for m in (members or []):
            if m in groups_by_name:
                dfs(m, stack + [name])

    for name in groups_by_name:
        dfs(name, [])
    return errs


def _group_double_count_errors(groups_by_name, engagement_names) -> list[str]:
    """A group must not count any engagement more than once — reachable both
    directly and through a sub-group (ancestor/descendant), or via two sub-groups.
    Summing such a config double-counts the rollup, so reject it loudly. Assumes
    no cycles (checked first, so the multiset walk terminates)."""
    eng = set(engagement_names)
    errs: list[str] = []

    def expand(name, seen):
        if name in seen:
            return []
        seen = seen | {name}
        members = groups_by_name.get(name)
        if _is_wildcard(members):
            # A wildcard subgroup can't be expanded to a member multiset, so a
            # "diamond" through it (e.g. [AllOfThem("*"), Billable]) is not
            # flagged here — resolve_group_engagements' unconditional dedupe
            # keeps the numbers correct regardless.
            return []
        out: list[str] = []
        for m in (members or []):
            if m in groups_by_name:
                out.extend(expand(m, seen))
            elif m in eng:
                out.append(m)
        return out

    for name in groups_by_name:
        counts: dict[str, int] = {}
        for e in expand(name, set()):
            counts[e] = counts.get(e, 0) + 1
        for e, n in counts.items():
            if n > 1:
                errs.append(
                    f"group '{name}' counts engagement '{e}' more than once "
                    f"(reachable via multiple members) — this double-counts its "
                    f"rollup; a member should belong to only one path."
                )
    return errs


def registry_child_path_errors(buckets) -> list[str]:
    """A registry `children:` bucket must live INSIDE its parent's source_path —
    splitting a bucket carves sub-paths out of it, so a child path not under the
    parent would silently miscount. Recurses to grandchildren."""
    errs: list[str] = []

    def walk(bs):
        for b in bs:
            parent = (b.get("source_path") or "").rstrip("/")
            for c in (b.get("children") or []):
                cp = (c.get("source_path") or "").rstrip("/")
                if parent and cp and not cp.startswith(parent + "/"):
                    errs.append(
                        f"registry bucket '{c.get('name')}' source_path '{cp}' is "
                        f"not under its parent '{b.get('name')}' ('{parent}') — a "
                        f"child bucket must live inside its parent's path."
                    )
            walk(b.get("children") or [])

    walk(buckets or [])
    return errs


def load_registry_buckets() -> list | None:
    """Top-level registry buckets (for the child-subpath check), or None when the
    registry file is absent/unreadable — validation then skips the registry rule."""
    try:
        with open(config.REGISTRY) as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return None
    return data.get("buckets")


# --- main ------------------------------------------------------------------

def main() -> None:
    wins = windows()
    widest_start, widest_end = wins["30d"]

    sess_path = run_scan(widest_start, widest_end)
    meet_path = run_fetch_meetings(widest_start, widest_end)
    prematch = run_prematch(sess_path, meet_path)

    confident_sessions = prematch["confident"]["sessions"]
    needs_llm_sessions = prematch["needs_llm"]["sessions"]
    # Split unattributable overhead (no file edits) from genuinely-resolvable sessions.
    overhead_sessions = [s for s in needs_llm_sessions if is_overhead_session(s)]
    resolvable_sessions = [s for s in needs_llm_sessions if not is_overhead_session(s)]

    # Cowork sessions live outside ~/.claude/projects/. The scanner normalizes
    # them into the CLI session shape and pre-classifies via slash command /
    # title regex / email default, so they slot straight into per_path_minutes
    # alongside CLI sessions — cross-surface even-split-fractional dedupe
    # happens for free.
    cowork_sessions = scan_cowork.scan(widest_start, widest_end)

    # Codex CLI sessions live outside ~/.claude/projects/ too (~/.codex/sessions/).
    # The scanner resolves each rollout's cwd to a bucket via the same registry
    # matcher CLI sessions use and returns CLI-shape session dicts (read in place —
    # rollouts already carry top-level UTC timestamps), so they slot straight into
    # per_path_minutes alongside CLI + Cowork sessions. When a /codex run shelled
    # out from a Claude Code session resolves to the SAME bucket as its parent
    # (the common case — same cwd), even_split_fractional's intra-bucket merge
    # counts the overlapping wall-clock once. (If the parent CLI session resolved
    # to a different/deeper bucket via file-evidence, the overlap even-splits
    # across buckets, like any other cross-bucket concurrency.)
    codex_sessions = scan_codex.scan(widest_start, widest_end)
    all_sessions = confident_sessions + cowork_sessions + codex_sessions

    # Load learnings for soft meeting resolution
    with open(config.LEARNINGS) as f:
        learnings = yaml.safe_load(f) or {}
    meetings, unresolved_meetings = all_resolved_meetings(prematch, learnings)
    still_unresolved_meetings = len(unresolved_meetings)

    by_window: dict[str, dict[str, float]] = {}
    for name, (ws, we) in wins.items():
        by_window[name] = per_path_minutes(all_sessions, meetings, ws, we)

    # Meeting-only minutes for the week, so the panel can break out meetings vs sessions.
    meeting_wtd = meeting_path_minutes(meetings, *wins["wtd"])

    appetite = load_appetite()
    groups_list = load_groups()
    groups_by_name = {g["name"]: g.get("members") for g in groups_list}
    # Loud preflight: a config that mixes income-mode with hour-cap vocabularies (a
    # dollar ceiling with no rate), an unknown/cyclic/double-counting group member
    # (#31), or a registry child bucket outside its parent (#31) would silently
    # mismeter — halt with a clear message rather than write wrong numbers. A nonzero
    # exit lands in pulse.stderr.log.
    errs = appetite_errors(appetite, groups=groups_by_name,
                           registry_buckets=load_registry_buckets())
    if errs:
        raise SystemExit("config error: " + "; ".join(errs))
    engagement_state: dict[str, dict] = {}
    for name, cfg in appetite.items():
        cfg = cfg or {}
        bucket = cfg.get("bucket", name)          # display name may differ from the ugly leaf
        h_today = find_hours(by_window["today"], bucket)
        h_wtd   = find_hours(by_window["wtd"],   bucket)
        h_7d    = find_hours(by_window["7d"],    bucket)
        h_30d   = find_hours(by_window["30d"],   bucket)
        if is_income_mode(cfg):
            # Income meter: $ billed for the calendar month (MTD hours × rate), with
            # an optional $ ceiling. Not an hour cap — day/week rows stay hours (no
            # weekly $ cap in v1); the dollar meter lives in the month view.
            bill_rate = float(cfg["bill_rate"])
            cap_value = cfg.get("monthly_cap_value")
            h_mtd = find_hours(by_window["mtd"], bucket)
            billed = income_billed(h_mtd, bill_rate)
            st_inc: dict = {
                "bucket":            bucket,
                "income_mode":       True,
                "track_only":        False,
                "bill_rate":         bill_rate,
                "monthly_cap_value": float(cap_value) if cap_value is not None else None,
                "weekly_cap_h":      None,
                "monthly_cap_h":     None,
                "today_h":           round(h_today, 2),
                "meeting_h":         round(find_hours(meeting_wtd, bucket), 2),
                "wtd": {"actual_h": round(h_wtd, 2)},
                "7d":  {"actual_h": round(h_7d,  2)},
                "30d": {"actual_h": round(h_30d, 2)},
                "mtd": {"actual_h": round(h_mtd, 2), "billed": round(billed)},
            }
            if cap_value is not None:
                st_inc["mtd"].update(dollars_remaining_or_over(billed, float(cap_value)))
            engagement_state[name] = st_inc
            continue
        weekly_cap, monthly_cap = engagement_caps(cfg)
        st: dict = {
            "bucket":        bucket,
            "track_only":    weekly_cap is None and monthly_cap is None,
            "weekly_cap_h":  round(weekly_cap,  2) if weekly_cap  is not None else None,
            "monthly_cap_h": round(monthly_cap, 2) if monthly_cap is not None else None,
            "today_h":       round(h_today, 2),
            "meeting_h":     round(find_hours(meeting_wtd, bucket), 2),
            "wtd": {"actual_h": round(h_wtd, 2)},
            "7d":  {"actual_h": round(h_7d,  2)},
            "30d": {"actual_h": round(h_30d, 2)},
        }
        if "monthly_value" in cfg:  # keep rate metadata when present (informational)
            st["monthly_value"] = cfg["monthly_value"]
            st["target_rate"]   = cfg.get("target_rate")
        if weekly_cap is not None:
            st["wtd"].update(remaining_or_over(h_wtd, weekly_cap))
            st["7d"].update(remaining_or_over(h_7d,  weekly_cap))
        if monthly_cap is not None:
            st["30d"].update(remaining_or_over(h_30d, monthly_cap))
        engagement_state[name] = st

    # Remainder engagements (e.g. Shaner Consulting = SC parent minus its billable +
    # Redacted/Pipeline children) — must run BEFORE groups so the roll-ups see the
    # adjusted hours. Canonical paths come from the widest window.
    remainder_names = [n for n, c in appetite.items() if (c or {}).get("remainder")]
    if remainder_names:
        canon = {n: _full_path_for(by_window["30d"], engagement_state[n]["bucket"])
                 for n in engagement_state}
        apply_remainder(engagement_state, canon, remainder_names)

    # User-defined roll-up groups (#31: nested). A group's members may name other
    # groups as well as engagements; resolution expands sub-groups into their leaf
    # engagements (de-duplicated, so nothing is double-counted) and the forest is
    # emitted in tree order with a `depth` for indented rendering. A flat config
    # (no group names another group) is depth-0 in definition order — the same rows
    # as before nesting existed. '*' = every defined engagement.
    group_blocks: list[dict] = []
    gdef_by_name = {g["name"]: g for g in groups_list}
    eng_names = list(engagement_state.keys())
    for name, depth in group_tree_order(groups_list):
        gdef = gdef_by_name[name]
        present = resolve_group_engagements(name, groups_by_name, eng_names)
        block = build_group_block(name, present, engagement_state,
                                  gdef.get("weekly_hours"), gdef.get("monthly_hours"),
                                  depth)
        # Direct engagement members (#66): the frontends nest these rows inside
        # this group's subtree instead of a flat top-level engagement list.
        block["direct_engagements"] = direct_engagement_members(
            gdef.get("members"), eng_names)
        # Soft overlap guard: if one member's bucket path is an ancestor of another's,
        # the sum double-counts. Detect via the resolved 30d paths and warn (never crash).
        overlap = _group_overlap(present, engagement_state, by_window["30d"])
        if overlap:
            block["overlap"] = overlap
        group_blocks.append(block)

    # Standalone has no deploy-week checkout, so there's no "last /deploy-week run"
    # timestamp to read. The key is kept (None) for state.json shape stability; no
    # frontend currently surfaces it.
    last_dw = None

    generated_at = datetime.now(LOCAL_TZ).isoformat(timespec="seconds")
    # Dump the unresolved work for setup/RESOLVE.md (run in Claude Code) to act on.
    write_uncategorized(resolvable_sessions, unresolved_meetings, generated_at)

    # "Update available" check (#25): compare local HEAD to shanerconsulting/pulse main.
    # Runs here so it rides the snapshot interval (throttled, off the main thread in this
    # pipeline subprocess) and lands in state.json as one atomic write. Fully fail-silent
    # — a network/parse failure carries the prior block forward and never aborts the
    # snapshot (a stale card is better than no card). Only git shas cross the wire (#8).
    prior_uc = _read_prior_update_check()
    try:
        update_check = updatecheck.run_check(
            config.DATA_DIR, datetime.now(LOCAL_TZ), prior=prior_uc) or prior_uc
    except Exception:
        update_check = prior_uc

    state = {
        "generated_at":         generated_at,
        "repo_path":            str(config.DATA_DIR),
        "windows_raw_minutes":  by_window,
        "groups":               group_blocks,
        "engagements":          engagement_state,
        "live_bucket":          None,  # filled in by Phase 2 (live_bucket.py)
        "needs_llm": {
            "sessions": len(resolvable_sessions),
            "meetings": still_unresolved_meetings,
        },
        "overhead_sessions": len(overhead_sessions),
        "uncategorized_detail": uncategorized_detail(resolvable_sessions, unresolved_meetings),
        "meeting_breakdown": {
            "total_resolved": len(meetings),
            "soft_resolved": sum(1 for m in meetings if m.get("reason") == "soft_resolved_unambig_co_attendee"),
            "still_unresolved": still_unresolved_meetings,
        },
        "meetings_wtd": meetings_in_window(meetings, *wins["wtd"]),
        "people": build_people(learnings),
        "last_deploy_week_run": last_dw,
        "update_check": update_check,
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
        if st.get("income_mode"):
            mtd = st["mtd"]
            cap = st.get("monthly_cap_value")
            if cap:
                d = f"OVER ${mtd['dollars_over']:,}" if mtd.get("over") else f"${mtd['dollars_left']:,} left"
                print(f"  {name:18} mtd ${mtd['billed']:,}/${cap:,.0f}  {d}")
            else:
                print(f"  {name:18} mtd ${mtd['billed']:,}  (running meter, ${st['bill_rate']:,.0f}/hr)")
            continue
        if st.get("track_only"):
            print(f"  {name:18} wtd {wtd['actual_h']:5.1f}h  (tracked, no cap)")
            continue
        status = f"OVER {wtd['hours_over']}h" if wtd["over"] else f"{wtd['hours_left']}h left"
        print(f"  {name:18} wtd {wtd['actual_h']:5.1f}/{st['weekly_cap_h']:>4.1f}h  {status}")
    for g in group_blocks:
        wtd = g["wtd"]
        indent = "  " * g.get("depth", 0)
        if g.get("weekly_cap_h") is None:      # capless nested roll-up — hours only
            print(f"  {indent}[{g['name']:16}] wtd {wtd['actual_h']:5.1f}h  (rolls up, no cap)")
        else:
            status = f"OVER {wtd['hours_over']}h" if wtd["over"] else f"{wtd['hours_left']}h left"
            print(f"  {indent}[{g['name']:16}] wtd {wtd['actual_h']:5.1f}/{g['weekly_cap_h']:>4.1f}h  {status}")
        for w in g.get("overlap", []):
            print(f"    {indent}! overlap: {w}")


if __name__ == "__main__":
    main()
