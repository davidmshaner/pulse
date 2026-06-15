"""test_install_venv.py — the install path must put deps in the same interpreter
the LaunchAgent runs (#15).

Page West's fresh install crash-looped on ModuleNotFoundError: the docs ran a
bare `pip3 install` (Homebrew interpreter, blocked by PEP 668; unpinned pyobjc
built from source and failed), while the plist ran `/usr/bin/python3`. The fix:
install-mac.sh builds a repo-local venv from /usr/bin/python3, installs a pinned
requirements.txt into it (prebuilt wheels, no PEP 668), and the plist + app run
that venv's interpreter — so install-time deps and runtime are one interpreter.

These are structural assertions on the install wiring; behavioral validation (a
real venv install + launch) is the QA step.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = (ROOT / "install-mac.sh").read_text()
APP = (ROOT / "src" / "pulse" / "app.py").read_text()
REQS = ROOT / "requirements.txt"


def test_requirements_pins_app_deps():
    assert REQS.exists(), "requirements.txt must exist"
    text = REQS.read_text()
    for pkg in ("pyobjc-core==", "pyobjc-framework-Cocoa==",
                "pyobjc-framework-WebKit==", "rumps==", "PyYAML=="):
        assert pkg in text, f"{pkg} must be pinned in requirements.txt"


def test_requirements_pins_calendar_deps():
    # The calendar fetch (fetch_meetings.py) imports the Google client only when a
    # calendar is configured. If those libs aren't in requirements.txt, the
    # LaunchAgent's .venv can't import them and every meeting silently drops from
    # the totals (#26). They must be pinned here so a reinstall can't lose them.
    text = REQS.read_text()
    for pkg in ("google-auth==", "google-auth-oauthlib==",
                "google-api-python-client=="):
        assert pkg in text, f"{pkg} must be pinned in requirements.txt (calendar fetch, #26)"


def test_installer_builds_venv_from_system_python():
    assert "/usr/bin/python3 -m venv" in INSTALLER, "venv must be built from system python3"
    assert "requirements.txt" in INSTALLER, "deps must install from requirements.txt"


def test_plist_runs_the_venv_interpreter():
    # The LaunchAgent must run the venv's python (which has the deps), not the
    # bare system interpreter the deps may not be installed into.
    assert ".venv/bin/python3</string>" in INSTALLER
    assert "<string>/usr/bin/python3</string><string>-u</string>" not in INSTALLER


def test_dep_install_failure_surfaces():
    pip_lines = [l for l in INSTALLER.splitlines()
                 if "pip install" in l and "requirements.txt" in l]
    assert pip_lines, "expected a `pip install -r requirements.txt` line"
    for l in pip_lines:
        assert "|| true" not in l, "the dep install must not swallow failures with `|| true`"


def test_app_runs_snapshot_via_sys_executable():
    # app.py must invoke snapshot under its own interpreter (the venv), not a
    # hardcoded /usr/bin/python3, so snapshot inherits the venv's deps.
    assert "sys.executable" in APP
    assert '"/usr/bin/python3", str(SNAPSHOT_SCRIPT)' not in APP
