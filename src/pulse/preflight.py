"""preflight.py — launch self-check for the Pulse macOS menu-bar app (#18).

A fresh install can fail two ways that both surface as a KeepAlive crash loop with
one opaque line in .cache/pulse.stderr.log:
  - a dep missing (or broken) in the interpreter the LaunchAgent runs (ImportError)
  - a working directory launchd's python can't read (macOS TCC → 'Operation not permitted')

This runs BEFORE app.py's heavy pyobjc imports and turns either into one
human-readable, actionable line. It does NOT stop the relaunch — launchd's
KeepAlive still restarts the process — but every iteration now logs a clear fix
instead of a raw traceback. (The pure case where launchd can't read the clone at
all is caught at install time by #16, since the interpreter can't even read this
file to run the check.)

This is the macOS app path (app.py); the Windows overlay (app_win.py) is separate.
The module itself imports with the stdlib only — the dep imports happen inside the
check, guarded — so it loads even when the real deps are absent.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

# The third-party modules app.py imports at startup (pyobjc set + pyyaml via
# config). Mirrors app.py's top-level imports; test_preflight asserts these all
# import on a configured machine, so a typo or drift here fails fast.
REQUIRED_MODULES = ["AppKit", "WebKit", "objc", "Foundation", "yaml"]

_FIX = "reinstall the deps: bash install-mac.sh"


def unimportable_modules(modules):
    """Modules that can't be imported — missing OR present-but-broken. Actually
    imports each (app.py is about to anyway), so an ABI-mismatched/half-installed
    package is caught too, not just an absent one."""
    bad = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception:  # ModuleNotFoundError, or a C-extension init error
            bad.append(name)
    return bad


def working_dir_problem(working_dir):
    """Problem line if the working dir can't actually be read, else None. Uses a
    real os.listdir probe rather than os.access, so a TCC denial (which leaves the
    POSIX bits readable but blocks launchd) still surfaces as PermissionError."""
    path = Path(working_dir)
    try:
        os.listdir(path)
        return None
    except FileNotFoundError:
        return f"Pulse's working directory does not exist: {path} — {_FIX}"
    except PermissionError:
        return (f"Pulse cannot read its working directory: {path} — macOS may be "
                f"blocking it (TCC). Move the clone to an unprotected folder and {_FIX}.")
    except OSError as e:
        return f"Pulse cannot read its working directory: {path} ({e.strerror}) — {_FIX}"


def problems(working_dir, modules=REQUIRED_MODULES):
    """All preflight problems as human-readable lines (empty when healthy)."""
    out = []
    bad = unimportable_modules(modules)
    if bad:
        out.append(f"Pulse can't import required module(s): {', '.join(bad)} — {_FIX}")
    wd = working_dir_problem(working_dir)
    if wd:
        out.append(wd)
    return out


def run_or_exit(*, working_dir=None, modules=REQUIRED_MODULES, selftest=False, out=None):
    """Run the preflight. On any problem, print each line and exit nonzero (launchd's
    KeepAlive will relaunch, but the log line is now actionable). With selftest=True
    and no problems, print OK and exit zero. Otherwise return None so the caller
    (app.py) continues to its real imports."""
    if out is None:
        out = sys.stderr
    if working_dir is None:
        working_dir = Path.cwd()
    found = problems(working_dir, modules)
    if found:
        for line in found:
            print(line, file=out)
        sys.exit(1)
    if selftest:
        print("Pulse preflight OK: deps importable, working directory readable.",
              file=sys.stdout)
        sys.exit(0)
    return None


if __name__ == "__main__":
    # `python3 src/pulse/preflight.py [--selftest]` — run the checks on demand.
    run_or_exit(selftest="--selftest" in sys.argv)
