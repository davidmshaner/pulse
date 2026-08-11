"""test_render_hero.py — the README hero tool must track the panel VM shape (#66).

The hero once shipped frozen on a pre-day/week/month row shape and rendered an
empty card silently. Building DEMO through build_view_model prevents drift; this
smoke test fails loudly if the demo ever stops producing rows the template reads.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src" / "pulse"))

import render_hero  # noqa: E402


def test_demo_view_model_has_rendered_rows():
    rows = render_hero.DEMO.get("rows")
    assert rows, "hero DEMO produced no rows — the card would render empty"
    names = [r["name"] for r in rows]
    assert "client-app" in names and len(names) == 4
    # the over-cap demo engagement must carry a real week cell the template reads
    over = [r for r in rows if r["name"] == "client-app"][0]
    assert over["week"]["status"] == "over" and over["week"]["cap_h"] == 12.0
