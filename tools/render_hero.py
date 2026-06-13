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

PANEL = ROOT / "src" / "pulse" / "panel"
TEMPLATE = (PANEL / "template.html").read_text()
HERO_HTML = PANEL / "_hero.html"           # gitignored; lives in panel/ so fonts/ resolve
OUT = ROOT / "assets" / "hero.png"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

DEMO = {
    "generated_at": "2026-06-12T09:41:00-04:00",
    "total": None,
    "engagements": [
        {"name": "client-app", "actual_h": 14.2, "cap_h": 12.0, "pct": 118,
         "status": "over", "today_h": 2.1, "d7_h": 15.0, "d30_actual": 58.0, "d30_cap": 48.0},
        {"name": "mobile-app", "actual_h": 9.5, "cap_h": 10.0, "pct": 95,
         "status": "near", "today_h": 1.0, "d7_h": 9.5, "d30_actual": 38.0, "d30_cap": 40.0},
        {"name": "open-source", "actual_h": 3.2, "cap_h": 8.0, "pct": 40,
         "status": "under", "today_h": 0.0, "d7_h": 3.2, "d30_actual": 12.0, "d30_cap": 32.0},
        {"name": "writing", "actual_h": 1.1, "cap_h": 4.0, "pct": 28,
         "status": "under", "today_h": 0.5, "d7_h": 1.1, "d30_actual": 5.0, "d30_cap": 16.0},
    ],
    "now": {"label": "client-app", "elapsed_min": 7},
    "uncategorized": {"sessions": 2, "meetings": 3},
}

WINDOW_W = 396
WINDOW_H = 322


def main() -> None:
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
