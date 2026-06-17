"""frontend_common.py — pure state→text painting shared by the macOS menu bar
(pulse.py) and the Windows overlay (pulse_win.py). No UI-framework imports."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# The snapshot loop refreshes every 600s. If state.json is older than ~2.5 cycles the
# refresh has stalled (pipeline killed before its final write); the card should say so
# rather than keep painting old numbers as if current. See runner.py / issue #28.
STALE_AFTER_SECONDS = 1500
STALE_MARK = "⋯"


def is_stale(state: dict | None, now: datetime | None = None,
             max_age_seconds: int = STALE_AFTER_SECONDS) -> bool:
    """True when the card's data is too old to trust (or absent/unparseable).

    `now` is injectable for testing; when omitted it's read in the state's own tz so
    the comparison is apples-to-apples with the tz-aware `generated_at`.
    """
    if not state:
        return True
    gen = state.get("generated_at")
    if not gen:
        return True
    try:
        ts = datetime.fromisoformat(gen)
    except (TypeError, ValueError):
        return True
    if now is None:
        now = datetime.now(ts.tzinfo)
    elif ts.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=ts.tzinfo)
    elif ts.tzinfo is None and now.tzinfo is not None:
        ts = ts.replace(tzinfo=now.tzinfo)
    return (now - ts).total_seconds() > max_age_seconds


def load_state(widget_dir: Path) -> dict | None:
    state = widget_dir / "state.json"
    if not state.exists():
        return None
    try:
        with open(state) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def bar(actual: float, total: float, width: int = 10) -> str:
    if total <= 0:
        return "·" * width
    frac = max(0.0, min(1.0, actual / total))
    n = int(round(frac * width))
    return "█" * n + "·" * (width - n)


def fmt_period(d: dict) -> str:
    if d["over"]:
        return f"OVER {d['hours_over']}h"
    return f"{d['hours_left']}h left"


def _abbr(name: str) -> str:
    """Two-char abbreviation, derived generically (no hardcoded names)."""
    return name[:2]


def title_for(state: dict | None, stale: bool = False) -> str:
    """Menu-bar title. When `stale`, prefix a mark so a frozen refresh is visible
    (the underlying value is kept, not blanked — it's the last-known reading)."""
    base = _title_base(state)
    if stale and state is not None:
        return STALE_MARK + base
    return base


def _title_base(state: dict | None) -> str:
    if state is None:
        return "Pulse"
    lb = state.get("live_bucket")
    engagements = state.get("engagements", {})
    # Only capped (billable) engagements drive the glyph — track-only rows have no
    # over/hours_left and aren't part of the billable-governor signal.
    capped = {n: e for n, e in engagements.items() if "over" in (e.get("wtd") or {})}
    if lb and lb.get("bucket_path"):
        leaf = lb["bucket_path"][-1]
        if leaf in capped:
            wtd = capped[leaf]["wtd"]
            ab = _abbr(leaf)
            if wtd["over"]:
                return f"⚠{ab} -{wtd['hours_over']:.0f}h"
            return f"{ab} {wtd['hours_left']:.0f}h"
    over = [(n, e["wtd"]["hours_over"]) for n, e in capped.items() if e["wtd"]["over"]]
    if over:
        worst = max(over, key=lambda t: t[1])
        return f"⚠{_abbr(worst[0])} -{worst[1]:.0f}h"
    if capped:
        total_left = sum(e["wtd"]["hours_left"] for e in capped.values())
        return f"✓ {total_left:.0f}h"
    return "Pulse"


def menu_lines(state: dict | None) -> list:
    """Flat list of text lines; None marks a separator. The rumps frontend wraps
    each line in a MenuItem; the overlay renders them as label text."""
    items: list = []
    if state is None:
        return ["(snapshot not yet run)"]
    groups = state.get("groups")
    if groups is None and state.get("total"):          # legacy state.json shape
        groups = [{**state["total"], "name": "Billable"}]
    for g in groups or []:
        wtd, d7, d30 = g["wtd"], g["7d"], g["30d"]
        dot = "● " if wtd["over"] else "  "
        items.append(f"{dot}{g['name'].upper()}  cap {g['weekly_cap_h']:.0f}h/wk  {g['monthly_cap_h']:.0f}h/mo")
        items.append(f"  {bar(wtd['actual_h'], g['weekly_cap_h'])}  "
                     f"wtd {wtd['actual_h']:.1f}/{g['weekly_cap_h']:.0f}h   {fmt_period(wtd)}")
        items.append(f"  today {g['today_h']:.1f}h  ·  7d {d7['actual_h']:.1f}h  ·  "
                     f"30d {d30['actual_h']:.0f}/{g['monthly_cap_h']:.0f}h")
        items.append(None)
    for name, eng in state.get("engagements", {}).items():
        wtd, d7, d30 = eng["wtd"], eng["7d"], eng["30d"]
        if eng.get("track_only"):
            items.append(f"  {name}  (tracked, no cap)")
            items.append(f"  today {eng['today_h']:.1f}h  ·  7d {d7['actual_h']:.1f}h  ·  "
                         f"30d {d30['actual_h']:.0f}h")
            items.append(None)
            continue
        dot = "● " if wtd["over"] else "  "
        items.append(f"{dot}{name}  cap {eng['weekly_cap_h']:.1f}h/wk  {eng['monthly_cap_h']:.0f}h/mo")
        items.append(f"  {bar(wtd['actual_h'], eng['weekly_cap_h'])}  "
                     f"wtd {wtd['actual_h']:.1f}/{eng['weekly_cap_h']:.1f}h   {fmt_period(wtd)}")
        items.append(f"  today {eng['today_h']:.1f}h  ·  7d {d7['actual_h']:.1f}h  ·  "
                     f"30d {d30['actual_h']:.0f}/{eng['monthly_cap_h']:.0f}h")
        items.append(None)
    lb = state.get("live_bucket")
    if lb:
        bp_str = ".".join(lb.get("bucket_path") or ["?"])
        items.append(f"NOW: {bp_str}  (~{lb['last_active_minutes_ago']:.0f} min)")
    else:
        items.append("NOW: (no recent activity)")
    n_sess = state.get("needs_llm", {}).get("sessions", 0)
    n_meet = state.get("needs_llm", {}).get("meetings", 0)
    if n_sess or n_meet:
        items.append(f"uncategorized: {n_sess} sessions, {n_meet} meetings")
    generated = state.get("generated_at")
    if generated:
        items.append(f"snapshot: {generated[11:16]}")
    return items
