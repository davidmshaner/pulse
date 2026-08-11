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

# Flat sibling import, like every module in src/pulse: callers put src/pulse on
# sys.path (app.py, app_win.py, the tests) — `panel` is a top-level package
# there, so a relative import can't reach the sibling module.
import frontend_common


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
    over = billed > cap_value
    # A $ cap is a hard ceiling: any strict overage renders red, so the bar
    # never disagrees with the "$X over" verdict in the 100-105% band.
    cell = {"income": True, "billed": billed, "cap_value": cap_value,
            "pct": pct, "status": "over" if over else _status(pct), "over": over}
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


def _row(name: str, blk: dict, is_group: bool, depth: int = 0) -> dict:
    if blk.get("income_mode"):
        row = _income_row(name, blk, is_group)
    else:
        # A capless roll-up group renders track-style (hours, no bar), like a
        # track-only engagement; a capped group keeps its bar. (Before nested
        # groups, every group was capped, so this only affects nested roll-ups.)
        track_only = bool(blk.get("track_only"))
        row = {
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
    # `depth` drives indented rendering of nested groups (#31). Emitted ONLY when
    # nonzero, so a flat (depth-0) config's view model — and its rendered DOM — is
    # byte-identical to before nesting existed.
    if depth:
        row["depth"] = depth
    return row


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


def _sort_sibling_engagements(rows: list) -> list:
    """Apply the engagement ordering — capped-over first, then other capped
    (alpha), then track-only (alpha) — per SIBLING SET instead of globally (#66).
    iter_rows emits each parent's members contiguously (and adjacent sets always
    differ in depth), so sibling sets are exactly the maximal same-depth runs of
    engagement rows; group rows pass through in place. A flat config is one big
    run, i.e. the old global sort."""
    key = lambda x: (x["track_only"], x["week"]["status"] != "over", x["name"])  # noqa: E731
    out: list = []
    run: list = []

    def flush():
        run.sort(key=key)
        out.extend(run)
        run.clear()

    for row in rows:
        if row["is_group"]:
            flush()
            out.append(row)
        else:
            if run and run[-1].get("depth", 0) != row.get("depth", 0):
                flush()
            run.append(row)
    flush()
    return out


def build_view_model(state: dict) -> dict:
    # One interleaved row list (#66): the shared iter_rows walk nests each
    # group's member engagements inside its subtree; the template renders
    # VM.rows top to bottom.
    rows = _sort_sibling_engagements([
        _row(name, blk, kind == "group", depth)
        for kind, name, blk, depth in frontend_common.iter_rows(state)
    ])

    now = None
    lb = state.get("live_bucket")
    if lb and lb.get("bucket_path"):
        now = {"label": " · ".join(lb["bucket_path"]),
               "elapsed_min": lb.get("elapsed_min", 0)}

    return {
        "generated_at": state.get("generated_at"),
        "repo_path": state.get("repo_path", ""),
        "rows": rows,
        "now": now,
        "uncategorized": state.get("needs_llm", {"sessions": 0, "meetings": 0}),
        "overhead_sessions": state.get("overhead_sessions", 0),
        "uncategorized_detail": state.get("uncategorized_detail", {"sessions": [], "meetings": []}),
        "meetings_wtd": state.get("meetings_wtd", 0),
        "people": state.get("people", []),
        "update": _update(state),
    }
