"""test_preflight.py — Pulse's launch preflight (#18).

Both first-run failures Page West hit (a missing dep → ModuleNotFoundError, and a
TCC-blocked working dir → 'Operation not permitted') surfaced identically: a
KeepAlive crash loop with one opaque traceback. preflight runs before the heavy
pyobjc imports and turns each into one human-readable line. It's stdlib-only so
this test never imports pyobjc/rumps.
"""
import os
import sys
from pathlib import Path

import pytest

WIDGET = Path(__file__).resolve().parent.parent / "src" / "pulse"
sys.path.insert(0, str(WIDGET))

import importlib.util  # noqa: E402

import preflight  # noqa: E402

_IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def test_no_problems_when_deps_present_and_dir_readable(tmp_path):
    # 'sys' and 'os' always import; a readable tmp dir is fine.
    assert preflight.problems(working_dir=tmp_path, modules=["sys", "os"]) == []


def test_default_required_modules_import_on_a_configured_machine(tmp_path):
    # On a machine with the app deps installed (the dev / install target), the real
    # REQUIRED_MODULES must all import — guards against a typo or drift in the list.
    if importlib.util.find_spec("AppKit") is None:
        pytest.skip("pyobjc not installed in this interpreter")
    assert preflight.problems(working_dir=tmp_path) == []


def test_missing_module_is_reported_with_fix(tmp_path):
    probs = preflight.problems(working_dir=tmp_path,
                               modules=["sys", "this_module_does_not_exist_xyz"])
    assert len(probs) == 1
    line = probs[0]
    assert "this_module_does_not_exist_xyz" in line
    assert "install-mac.sh" in line, "should name the actionable fix"


@pytest.mark.skipif(_IS_ROOT, reason="root bypasses POSIX mode bits, so 0o000 stays readable")
def test_unreadable_working_dir_is_reported(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o000)
    try:
        probs = preflight.problems(working_dir=blocked, modules=["sys"])
    finally:
        blocked.chmod(0o755)  # restore so tmp cleanup works
    assert any(str(blocked) in p for p in probs), probs
    assert any("read" in p.lower() or "tcc" in p.lower() for p in probs), probs


def test_nonexistent_working_dir_is_reported(tmp_path):
    missing = tmp_path / "gone"
    probs = preflight.problems(working_dir=missing, modules=["sys"])
    assert any(str(missing) in p for p in probs), probs


def test_run_or_exit_aborts_on_missing_dep(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        preflight.run_or_exit(working_dir=tmp_path,
                              modules=["this_module_does_not_exist_xyz"])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "this_module_does_not_exist_xyz" in err


def test_run_or_exit_selftest_ok_exits_zero(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        preflight.run_or_exit(working_dir=tmp_path, modules=["sys", "os"], selftest=True)
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "ok" in out.lower()


def test_run_or_exit_returns_when_healthy_and_not_selftest(tmp_path):
    # Healthy + not selftest: must NOT exit (let the app continue to its imports).
    assert preflight.run_or_exit(working_dir=tmp_path, modules=["sys", "os"]) is None
