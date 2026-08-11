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


def fmt_dollars(v: float) -> str:
    """Whole dollars with a thousands separator: 6250 -> '$6,250'."""
    return f"${v:,.0f}"


def fmt_dollars_period(d: dict) -> str:
    """The $ analog of fmt_period: '$1,750 left' under a cap, or 'OVER $1,000'."""
    if d.get("over"):
        return f"OVER {fmt_dollars(d['dollars_over'])}"
    return f"{fmt_dollars(d['dollars_left'])} left"


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


def iter_rows(state: dict) -> list:
    """The shared render-order walk (#66): one (kind, name, block, depth) list both
    frontends consume. Groups arrive in snapshot tree order (with `depth`); each
    group's DIRECT engagement members (its `direct_engagements`, absent on old
    state.json -> no nesting) are held on a stack and emitted when the walk leaves
    that group's subtree — so a section reads group, sub-group subtrees, then its
    own engagements, one level deeper. An engagement claimed by two groups renders
    once, under its DEEPEST listing parent (most-specific wins; a tie keeps the
    first in tree order) — so a parent that also lists a sub-group's engagement
    doesn't steal it from the sub-group. Engagements in no group come last at
    depth 0, exactly the pre-#66 flat tail."""
    engs = state.get("engagements", {}) or {}
    groups = state.get("groups")
    if groups is None and state.get("total"):          # legacy state.json shape
        groups = [{**state["total"], "name": "Billable"}]
    groups = groups or []

    # Ownership pre-pass: engagement -> (depth, group index) of its deepest
    # listing group; only a strictly deeper claim replaces, so ties keep the
    # first tree-order parent.
    owner: dict = {}
    for i, g in enumerate(groups):
        d = g.get("depth", 0)
        for m in g.get("direct_engagements") or []:
            if m in engs and (m not in owner or d > owner[m][0]):
                owner[m] = (d, i)

    out: list = []
    stack: list = []                                   # (group depth, held member rows)

    def flush(depth):
        while stack and stack[-1][0] >= depth:
            out.extend(stack.pop()[1])

    for i, g in enumerate(groups):
        d = g.get("depth", 0)
        flush(d)
        out.append(("group", g["name"], g, d))
        held = []
        for m in g.get("direct_engagements") or []:
            if owner.get(m, (None, None))[1] == i and not any(h[1] == m for h in held):
                held.append(("engagement", m, engs[m], d + 1))
        stack.append((d, held))
    flush(0)
    for name, eng in engs.items():
        if name not in owner:
            out.append(("engagement", name, eng, 0))
    return out


def _group_lines(g: dict, items: list) -> None:
    """One group's menu lines. Nested groups (#31) indent by depth; a capless
    roll-up shows hours only. depth 0 + a cap -> the exact pre-nesting lines."""
    d7, d30 = g["7d"], g["30d"]
    ind = "  " * g.get("depth", 0)
    if g.get("weekly_cap_h") is None:
        items.append(f"{ind}  {g['name'].upper()}  (rolls up, no cap)")
        items.append(f"{ind}  today {g['today_h']:.1f}h  ·  7d {d7['actual_h']:.1f}h  ·  "
                     f"30d {d30['actual_h']:.0f}h")
        items.append(None)
        return
    wtd = g["wtd"]
    dot = "● " if wtd["over"] else "  "
    items.append(f"{ind}{dot}{g['name'].upper()}  cap {g['weekly_cap_h']:.0f}h/wk  {g['monthly_cap_h']:.0f}h/mo")
    items.append(f"{ind}  {bar(wtd['actual_h'], g['weekly_cap_h'])}  "
                 f"wtd {wtd['actual_h']:.1f}/{g['weekly_cap_h']:.0f}h   {fmt_period(wtd)}")
    items.append(f"{ind}  today {g['today_h']:.1f}h  ·  7d {d7['actual_h']:.1f}h  ·  "
                 f"30d {d30['actual_h']:.0f}/{g['monthly_cap_h']:.0f}h")
    items.append(None)


def _engagement_lines(name: str, eng: dict, depth: int, items: list) -> None:
    """One engagement's menu lines. `depth` nests a group member one indent stop
    deeper than its parent (#66); depth 0 -> the exact pre-nesting lines."""
    ind = "  " * depth
    wtd, d7, d30 = eng["wtd"], eng["7d"], eng["30d"]
    if eng.get("income_mode"):
        # $ meter for the calendar month (#38). With a cap: bar toward the ceiling
        # + $-left/over. Without: a running total, no bar. Hours stay on the sub-line.
        mtd = eng["mtd"]
        rate = eng.get("bill_rate")
        cap = eng.get("monthly_cap_value")
        if cap:
            dot = "● " if mtd.get("over") else "  "
            items.append(f"{ind}{dot}{name}  cap {fmt_dollars(cap)}/mo  ({fmt_dollars(rate)}/hr)")
            items.append(f"{ind}  {bar(mtd['billed'], cap)}  "
                         f"mtd {fmt_dollars(mtd['billed'])}/{fmt_dollars(cap)}   {fmt_dollars_period(mtd)}")
        else:
            items.append(f"{ind}  {name}  ({fmt_dollars(rate)}/hr · running meter)")
            items.append(f"{ind}  {fmt_dollars(mtd['billed'])} billed this month")
        items.append(f"{ind}  today {eng['today_h']:.1f}h  ·  7d {d7['actual_h']:.1f}h  ·  "
                     f"mtd {mtd['actual_h']:.1f}h")
        items.append(None)
        return
    if eng.get("track_only"):
        items.append(f"{ind}  {name}  (tracked, no cap)")
        items.append(f"{ind}  today {eng['today_h']:.1f}h  ·  7d {d7['actual_h']:.1f}h  ·  "
                     f"30d {d30['actual_h']:.0f}h")
        items.append(None)
        return
    dot = "● " if wtd["over"] else "  "
    items.append(f"{ind}{dot}{name}  cap {eng['weekly_cap_h']:.1f}h/wk  {eng['monthly_cap_h']:.0f}h/mo")
    items.append(f"{ind}  {bar(wtd['actual_h'], eng['weekly_cap_h'])}  "
                 f"wtd {wtd['actual_h']:.1f}/{eng['weekly_cap_h']:.1f}h   {fmt_period(wtd)}")
    items.append(f"{ind}  today {eng['today_h']:.1f}h  ·  7d {d7['actual_h']:.1f}h  ·  "
                 f"30d {d30['actual_h']:.0f}/{eng['monthly_cap_h']:.0f}h")
    items.append(None)


def menu_lines(state: dict | None) -> list:
    """Flat list of text lines; None marks a separator. The rumps frontend wraps
    each line in a MenuItem; the overlay renders them as label text. Rows come
    interleaved from iter_rows (#66): each group's member engagements nest inside
    its subtree instead of a flat tail."""
    items: list = []
    if state is None:
        return ["(snapshot not yet run)"]
    for kind, name, blk, depth in iter_rows(state):
        if kind == "group":
            _group_lines(blk, items)
        else:
            _engagement_lines(name, blk, depth, items)
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
