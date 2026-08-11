#!/usr/bin/env python3
"""hero/render_hero.py — render the README hero from the SAME panel template.

Demonstrates the one-template-two-jobs idea: the card you see in the menu bar is
the card on the README. Uses neutral demo data (no real projects). Output: assets/hero.png.

Run: /usr/bin/python3 hero/render_hero.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "pulse"))
from panel.render_html import render_html  # noqa: E402
from panel.render_state import build_view_model  # noqa: E402

PANEL = ROOT / "src" / "pulse" / "panel"
TEMPLATE = (PANEL / "template.html").read_text()
HERO_HTML = PANEL / "_hero.html"           # gitignored; lives in panel/ so fonts/ resolve
OUT = ROOT / "assets" / "hero.png"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _eng(weekly_cap, monthly_cap, wtd, today, d7, d30):
    over = wtd > weekly_cap
    w = {"actual_h": wtd, "over": over,
         ("hours_over" if over else "hours_left"): round(abs(weekly_cap - wtd), 1)}
    return {"track_only": False, "weekly_cap_h": weekly_cap, "monthly_cap_h": monthly_cap,
            "today_h": today, "wtd": w, "7d": {"actual_h": d7}, "30d": {"actual_h": d30}}


# Neutral demo STATE fed through the real view-model builder, so the hero can
# never drift from the template's expected shape again (it shipped broken once,
# frozen on a pre-day/week/month row shape).
DEMO_STATE = {
    "generated_at": "2026-06-12T09:41:00-04:00",
    "engagements": {
        "client-app":  _eng(12.0, 48.0, 14.2, 2.1, 15.0, 58.0),
        "mobile-app":  _eng(10.0, 40.0,  9.5, 1.0,  9.5, 38.0),
        "open-source": _eng(8.0, 32.0,   3.2, 0.0,  3.2, 12.0),
        "writing":     _eng(4.0, 16.0,   1.1, 0.5,  1.1,  5.0),
    },
    "live_bucket": {"bucket_path": ["client-app"], "elapsed_min": 7},
    "needs_llm": {"sessions": 2, "meetings": 3},
}
DEMO = build_view_model(DEMO_STATE)

WINDOW_W = 396
WINDOW_H = 322


def main() -> None:
    assert DEMO.get("rows"), "demo view model produced no rows — hero would render empty"
    HERO_HTML.write_text(render_html(DEMO, TEMPLATE))
    OUT.parent.mkdir(exist_ok=True)
    subprocess.run([
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=2",
        f"--window-size={WINDOW_W},{WINDOW_H}",
        f"--screenshot={OUT}", f"file://{HERO_HTML}",
    ], check=True, capture_output=True)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
