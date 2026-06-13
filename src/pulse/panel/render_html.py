# panel/render_html.py
"""Inline a view model into the panel template. No fetch, no CORS — the data
lives in the rendered file, so both WKWebView and headless Chrome load it the same way."""
from __future__ import annotations

import json
from pathlib import Path

PLACEHOLDER = "/*__PULSE_VM__*/ null"
PANEL_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = PANEL_DIR / "template.html"
RENDERED_PATH = PANEL_DIR / "_rendered.html"


def render_html(vm: dict, template: str) -> str:
    # </ would prematurely close the inline <script>; escape it.
    payload = json.dumps(vm).replace("</", "<\\/")
    return template.replace(PLACEHOLDER, payload)


def write_rendered(vm: dict, dest: Path = RENDERED_PATH) -> Path:
    template = TEMPLATE_PATH.read_text()
    dest.write_text(render_html(vm, template))
    return dest
