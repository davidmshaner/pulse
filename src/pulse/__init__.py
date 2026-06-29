"""Pulse — local macOS menu-bar time tracker."""
from pathlib import Path as _Path


def _read_version() -> str:
    # VERSION lives at the repo root, three levels up from src/pulse/__init__.py.
    vf = _Path(__file__).resolve().parent.parent.parent / "VERSION"
    try:
        return vf.read_text().strip()
    except OSError:
        return "0+unknown"


__version__ = _read_version()
