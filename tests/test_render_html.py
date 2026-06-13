import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src' / 'pulse'))
from panel.render_html import render_html

TEMPLATE = "<html><body><script>window.__PULSE_VM__ = /*__PULSE_VM__*/ null;renderPulse(window.__PULSE_VM__);</script></body></html>"

def test_inlines_vm_as_valid_json():
    vm = {"engagements": [{"name": "Acme", "pct": 191}], "total": None}
    out = render_html(vm, TEMPLATE)
    assert "/*__PULSE_VM__*/" not in out
    # the inlined value must parse back to the same object
    start = out.index("window.__PULSE_VM__ = ") + len("window.__PULSE_VM__ = ")
    end = out.index(";renderPulse")
    assert json.loads(out[start:end]) == vm

def test_escapes_closing_script_tag():
    vm = {"label": "</script><x>"}
    out = render_html(vm, TEMPLATE)
    assert "</script><x>" not in out.split("renderPulse")[0]  # not broken out of the script
