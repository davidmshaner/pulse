#!/usr/bin/env python3
"""hero/render_og.py — render the GitHub social-preview (Open Graph) card.

1280x640 brand card: wordmark + tagline + pillars on the left, the hero panel on
the right. Reuses assets/hero.png. Output: assets/social-preview.png.

After running, upload the PNG at:
  github.com/davidmshaner/pulse  ->  Settings  ->  General  ->  Social preview

Run: /usr/bin/python3 hero/render_og.py
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "src" / "pulse" / "panel" / "fonts"
HERO = ROOT / "assets" / "hero.png"
OG_HTML = Path("/tmp/pulse_og.html")
OUT = ROOT / "assets" / "social-preview.png"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

HTML = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
@font-face{{font-family:'JBM';font-weight:400;src:url('file://{FONTS}/jetbrains-mono-400.woff2');}}
@font-face{{font-family:'JBM';font-weight:500;src:url('file://{FONTS}/jetbrains-mono-500.woff2');}}
@font-face{{font-family:'JBM';font-weight:600;src:url('file://{FONTS}/jetbrains-mono-600.woff2');}}
:root{{--cream:#F7F5F2;--ink:#2D2A26;--sage:#5B7B6A;--muted:#8A857D;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
html,body{{width:640px;height:320px;background:var(--cream);
  font-family:'JBM',monospace;color:var(--ink);overflow:hidden;}}
.wrap{{display:flex;width:100%;height:100%;align-items:center;padding:0 44px;gap:34px;}}
.left{{flex:1;}}
.mark{{font-size:64px;font-weight:600;letter-spacing:-1.5px;line-height:1;}}
.rule{{width:52px;height:3px;background:var(--sage);margin:22px 0 18px;}}
.tag{{font-size:22px;font-weight:500;line-height:1.42;max-width:380px;}}
.right{{flex-shrink:0;}}
.right img{{width:248px;border-radius:10px;
  box-shadow:0 10px 30px rgba(45,42,38,0.16);border:1px solid #E7E3DD;}}
</style></head><body>
<div class="wrap">
  <div class="left">
    <div class="mark">Pulse</div>
    <div class="rule"></div>
    <div class="tag">for Claude Code junkies who want to know where their time actually goes</div>
  </div>
  <div class="right"><img src="file://{HERO}"></div>
</div>
</body></html>"""


def main() -> None:
    OG_HTML.write_text(HTML)
    OUT.parent.mkdir(exist_ok=True)
    subprocess.run([
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=2", "--allow-file-access-from-files",
        "--window-size=640,320", f"--screenshot={OUT}", f"file://{OG_HTML}",
    ], check=True, capture_output=True)
    print("wrote", OUT, "(1280x640)")


if __name__ == "__main__":
    main()
