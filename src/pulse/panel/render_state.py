# panel/render_state.py
"""Pure translation of state.json into a display-ready view model.
No I/O, no rounding surprises — the panel HTML consumes only this shape.

Every row carries a `day`, `week`, and `month` block (today, wtd vs weekly cap,
30d vs monthly cap) so the panel's day|week|month toggle switches with no
recompute. Group rows (roll-ups) always have week/month caps; track-only
engagements carry `cap_h: null` with status "track" and render hours without a
bar. The `day` block is always cap-less (no daily cap exists), so every row
renders track-style under the day view."""
from __future__ import annotations


def _status(pct: float) -> str:
    if pct > 105:
        return "over"
    if pct >= 90:
        return "near"
    return "under"


def _window(actual: float, cap: float | None) -> dict:
    """One window's display cell. cap None/0 => track-only (no bar)."""
    if not cap:
        return {"actual_h": round(actual, 1), "cap_h": None, "pct": 0, "status": "track"}
    pct = round(actual / cap * 100)
    return {"actual_h": round(actual, 1), "cap_h": round(cap, 1), "pct": pct, "status": _status(pct)}


def _income_month(billed: float, cap_value: float | None) -> dict:
    """The month cell for an income engagement (#38): dollars, not hours. With a
    cap, a bar toward the $ ceiling plus $-left / $-over; without one, a pure
    running meter (no bar). pct/status are recomputed here so the bar renders like
    any other (under/near/over)."""
    billed = round(billed)
    if not cap_value:
        return {"income": True, "billed": billed, "cap_value": None,
                "pct": 0, "status": "track", "over": False}
    cap_value = round(cap_value)
    pct = round(billed / cap_value * 100) if cap_value else 0
    cell = {"income": True, "billed": billed, "cap_value": cap_value,
            "pct": pct, "status": _status(pct), "over": billed > cap_value}
    delta = cap_value - billed
    if delta >= 0:
        cell["dollars_left"] = delta
    else:
        cell["dollars_over"] = -delta
    return cell


def _income_row(name: str, blk: dict, is_group: bool) -> dict:
    """View row for a `bill_rate` engagement. Month view is the $ meter; day/week
    stay track-style hour cells (no weekly $ cap in v1)."""
    mtd = blk.get("mtd", {})
    return {
        "name": name,
        "is_group": is_group,
        "track_only": False,
        "income_mode": True,
        "bill_rate": blk.get("bill_rate"),
        "today_h": round(blk.get("today_h", 0) or 0, 1),
        "d7_h": round(blk.get("7d", {}).get("actual_h", 0) or 0, 1),
        "meeting_h": round(blk.get("meeting_h", 0) or 0, 1),
        "day":   _window(blk.get("today_h", 0) or 0, None),
        "week":  _window(blk.get("wtd", {}).get("actual_h", 0) or 0, None),
        "month": _income_month(mtd.get("billed", 0) or 0, blk.get("monthly_cap_value")),
        "overlap": [],
    }


def _row(name: str, blk: dict, is_group: bool) -> dict:
    if blk.get("income_mode"):
        return _income_row(name, blk, is_group)
    track_only = bool(blk.get("track_only")) and not is_group
    return {
        "name": name,
        "is_group": is_group,
        "track_only": track_only,
        "today_h": round(blk.get("today_h", 0) or 0, 1),
        "d7_h": round(blk.get("7d", {}).get("actual_h", 0) or 0, 1),
        "meeting_h": round(blk.get("meeting_h", 0) or 0, 1),
        # A day has no cap today, so `day` is always a cap-less track cell (hours,
        # no bar) — even for rows that are capped for the week/month.
        "day":   _window(blk.get("today_h", 0) or 0, None),
        "week":  _window(blk.get("wtd", {}).get("actual_h", 0) or 0, blk.get("weekly_cap_h")),
        "month": _window(blk.get("30d", {}).get("actual_h", 0) or 0, blk.get("monthly_cap_h")),
        "overlap": blk.get("overlap") or [],
    }


def _update(state: dict) -> dict | None:
    """Surface the 'you're behind shanerconsulting/pulse main' banner data, or None.

    Reads the `update_check` block snapshot.py writes (see updatecheck.py). Absent or
    `behind: False` => None => the card stays silent (no nagging when current, and old
    state.json without the block renders fine). When behind, hands the template the exact
    one-line update command, scoped to the user's own clone path."""
    uc = state.get("update_check") or {}
    if not uc.get("behind"):
        return None
    repo = state.get("repo_path") or ""
    cmd = "git pull && bash install-mac.sh"
    return {"command": f"cd {repo} && {cmd}" if repo else cmd}


def build_view_model(state: dict) -> dict:
    engagements = [_row(n, e, False) for n, e in state.get("engagements", {}).items()]
    # capped-over first, then other capped (alpha), then track-only (alpha)
    engagements.sort(key=lambda x: (x["track_only"], x["week"]["status"] != "over", x["name"]))

    raw_groups = state.get("groups")
    if raw_groups is None and state.get("total"):           # legacy state.json shape
        raw_groups = [{**state["total"], "name": "Billable"}]
    groups = [_row(g["name"], g, True) for g in (raw_groups or [])]

    now = None
    lb = state.get("live_bucket")
    if lb and lb.get("bucket_path"):
        now = {"label": " · ".join(lb["bucket_path"]),
               "elapsed_min": lb.get("elapsed_min", 0)}

    return {
        "generated_at": state.get("generated_at"),
        "repo_path": state.get("repo_path", ""),
        "groups": groups,
        "engagements": engagements,
        "now": now,
        "uncategorized": state.get("needs_llm", {"sessions": 0, "meetings": 0}),
        "overhead_sessions": state.get("overhead_sessions", 0),
        "uncategorized_detail": state.get("uncategorized_detail", {"sessions": [], "meetings": []}),
        "meetings_wtd": state.get("meetings_wtd", 0),
        "people": state.get("people", []),
        "update": _update(state),
    }
