#!/usr/bin/env python3
"""discover.py — machine discovery for Pulse setup. Detects OS, the Claude Code
projects dir, the Cowork sessions dir, and candidate work roots (decoded from
project-dir names, ranked by session count). Emits JSON for the setup skill.
Pure stdlib; no network."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def detect_os() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def cowork_dir_for(os_name: str) -> Path:
    if os_name == "macos":
        return Path.home() / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"
    if os_name == "windows":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(base) / "Claude" / "local-agent-mode-sessions"
    return Path.home() / ".config" / "Claude" / "local-agent-mode-sessions"


def decode_project_dir(encoded: str) -> Path | None:
    """Decode a project-dir name (cwd with '/' -> '-') back to a real path.
    Lossy because real dirs contain '-', so we only accept a decoding that
    resolves to an existing directory."""
    if not encoded or not encoded.startswith("-"):
        return None
    candidate = Path("/" + encoded[1:].replace("-", "/"))
    return candidate if candidate.is_dir() else None
