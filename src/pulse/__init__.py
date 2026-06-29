"""Pulse — local macOS menu-bar time tracker."""
from pathlib import Path as _Path


def _read_version() -> str:
    # VERSION lives at the repo root, three levels up from src/pulse/__init__.py.
    vf = _Path(__file__).resolve().parent.parent.parent / "VERSION"
    try:
        return vf.read_text().strip()
    except OSError:
        return "0+unknown"


def __getattr__(name: str) -> str:
    # PEP 562: resolve __version__ lazily so plain `import pulse` does no disk I/O;
    # VERSION stays the single source of truth (read only when the value is used).
    if name == "__version__":
        return _read_version()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
