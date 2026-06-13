"""frontend_common.py — pure state→text painting shared by the macOS menu bar
(pulse.py) and the Windows overlay (pulse_win.py). No UI-framework imports."""
from __future__ import annotations

import json
from pathlib import Path


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


def title_for(state: dict | None) -> str:
    if state is None:
        return "Pulse"
    lb = state.get("live_bucket")
    engagements = state.get("engagements", {})
    if lb and lb.get("bucket_path"):
        leaf = lb["bucket_path"][-1]
        if leaf in engagements:
            wtd = engagements[leaf]["wtd"]
            ab = _abbr(leaf)
            if wtd["over"]:
                return f"⚠{ab} -{wtd['hours_over']:.0f}h"
            return f"{ab} {wtd['hours_left']:.0f}h"
    over = [(n, e["wtd"]["hours_over"]) for n, e in engagements.items() if e["wtd"]["over"]]
    if over:
        worst = max(over, key=lambda t: t[1])
        return f"⚠{_abbr(worst[0])} -{worst[1]:.0f}h"
    if engagements:
        total_left = sum(e["wtd"]["hours_left"] for e in engagements.values())
        return f"✓ {total_left:.0f}h"
    return "Pulse"


def menu_lines(state: dict | None) -> list:
    """Flat list of text lines; None marks a separator. The rumps frontend wraps
    each line in a MenuItem; the overlay renders them as label text."""
    items: list = []
    if state is None:
        return ["(snapshot not yet run)"]
    total = state.get("total")
    if total:
        wtd, d7, d30 = total["wtd"], total["7d"], total["30d"]
        dot = "● " if wtd["over"] else "  "
        items.append(f"{dot}BILLABLE  cap {total['weekly_cap_h']:.0f}h/wk  {total['monthly_cap_h']:.0f}h/mo")
        items.append(f"  {bar(wtd['actual_h'], total['weekly_cap_h'])}  "
                     f"wtd {wtd['actual_h']:.1f}/{total['weekly_cap_h']:.0f}h   {fmt_period(wtd)}")
        items.append(f"  today {total['today_h']:.1f}h  ·  7d {d7['actual_h']:.1f}h  ·  "
                     f"30d {d30['actual_h']:.0f}/{total['monthly_cap_h']:.0f}h")
        items.append(None)
    for name, eng in state["engagements"].items():
        wtd, d7, d30 = eng["wtd"], eng["7d"], eng["30d"]
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
