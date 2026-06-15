"""test_standalone_pipeline.py — guards the standalone decoupling (#17).

The snapshot pipeline must shell out via ``sys.executable`` (not a bare ``python3``
that may resolve to an interpreter missing the deps — the break Page West hit on a
fresh install), and must read its categorization inputs from
``config.REGISTRY/LEARNINGS/RULES`` (repo-local on a clean clone), never a hardcoded
``deploy-week/context`` path.
"""
import sys
from datetime import datetime
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent / "src" / "pulse"
sys.path.insert(0, str(WIDGET))

import config  # noqa: E402
import snapshot  # noqa: E402


def _capture(monkeypatch):
    """Replace subprocess.run with a recorder; satisfy callers that read --out."""
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if "--out" in cmd:
            Path(cmd[cmd.index("--out") + 1]).write_text("{}")

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(snapshot.subprocess, "run", fake_run)
    return calls


def test_pipeline_shells_out_via_sys_executable(monkeypatch):
    calls = _capture(monkeypatch)
    now = datetime.now(config.LOCAL_TZ)
    snapshot.run_scan(now, now)
    snapshot.run_fetch_meetings(now, now)
    snapshot.run_prematch(Path("/tmp/s.json"), Path("/tmp/m.json"))
    assert calls, "expected the pipeline to invoke subprocess.run"
    for cmd in calls:
        assert cmd[0] == sys.executable, f"pipeline used a non-parent interpreter: {cmd[0]!r}"


def test_prematch_reads_repo_local_categorization_inputs(monkeypatch):
    calls = _capture(monkeypatch)
    snapshot.run_prematch(Path("/tmp/s.json"), Path("/tmp/m.json"))
    cmd = calls[-1]
    reg = cmd[cmd.index("--registry") + 1]
    learn = cmd[cmd.index("--learnings") + 1]
    rules = cmd[cmd.index("--rules") + 1]
    assert reg == str(config.REGISTRY), reg
    assert learn == str(config.LEARNINGS), learn
    assert rules == str(config.RULES), rules
