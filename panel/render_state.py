# panel/render_state.py
"""Pure translation of state.json into a display-ready view model.
No I/O, no rounding surprises — the panel HTML consumes only this shape."""
from __future__ import annotations


def _status(pct: float) -> str:
    if pct > 105:
        return "over"
    if pct >= 90:
        return "near"
    return "under"


def _block(d: dict, cap_h: float, today_h: float,
           d30_actual: float, d30_cap: float) -> dict:
    actual = d["actual_h"]
    pct = round(actual / cap_h * 100) if cap_h else 0
    return {
        "actual_h": round(actual, 1),
        "cap_h": round(cap_h, 1),
        "pct": pct,
        "status": _status(pct),
        "today_h": round(today_h, 1),
        "d7_h": None,   # filled by caller (needs the 7d block)
        "d30_actual": round(d30_actual, 1),
        "d30_cap": round(d30_cap, 1),
    }


def _engagement(name: str, e: dict) -> dict:
    blk = _block(e["wtd"], e["weekly_cap_h"], e["today_h"],
                 e["30d"]["actual_h"], e["monthly_cap_h"])
    blk["name"] = name
    blk["d7_h"] = round(e["7d"]["actual_h"], 1)
    return blk


def build_view_model(state: dict) -> dict:
    engagements = [_engagement(n, e) for n, e in state.get("engagements", {}).items()]
    # over-budget first, then alphabetical
    engagements.sort(key=lambda x: (x["status"] != "over", x["name"]))

    total = None
    t = state.get("total")
    if t:
        total = _block(t["wtd"], t["weekly_cap_h"], t["today_h"],
                       t["30d"]["actual_h"], t["monthly_cap_h"])
        total["d7_h"] = round(t["7d"]["actual_h"], 1)

    now = None
    lb = state.get("live_bucket")
    if lb and lb.get("bucket_path"):
        now = {"label": " · ".join(lb["bucket_path"]),
               "elapsed_min": lb.get("elapsed_min", 0)}

    return {
        "generated_at": state.get("generated_at"),
        "total": total,
        "engagements": engagements,
        "now": now,
        "uncategorized": state.get("needs_llm", {"sessions": 0, "meetings": 0}),
    }
