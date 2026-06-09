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


def candidate_roots(top: int = 20) -> list[dict]:
    """Decode every project-dir to a real path, count session files per path,
    return [{path, session_count}] ranked desc. Skips unresolvable encodings."""
    pdir = projects_dir()
    out = []
    if pdir.is_dir():
        for child in pdir.iterdir():
            if not child.is_dir():
                continue
            decoded = decode_project_dir(child.name)
            if decoded is None:
                continue
            n = sum(1 for _ in child.glob("*.jsonl"))
            out.append({"path": str(decoded), "session_count": n})
    out.sort(key=lambda c: -c["session_count"])
    return out[:top]


def report() -> dict:
    os_name = detect_os()
    cowork = cowork_dir_for(os_name)
    return {
        "os": os_name,
        "projects_dir": str(projects_dir()),
        "projects_dir_exists": projects_dir().is_dir(),
        "cowork_dir": str(cowork),
        "cowork_dir_exists": cowork.is_dir(),
        "candidate_roots": candidate_roots(),
    }


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
