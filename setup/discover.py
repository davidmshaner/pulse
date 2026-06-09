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


def _cwd_from_session(jsonl_path: Path) -> str | None:
    """Read the working directory recorded inside a session JSONL. The first
    entries can be queue/summary lines without a cwd, so scan a few lines until
    one carries it. Robust where the dir-name decode is not (Claude Code maps
    '/', '_', and '.' all to '-' in the dir name, which is irreversible)."""
    try:
        with open(jsonl_path) as f:
            for i, line in enumerate(f):
                if i > 200:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                cwd = obj.get("cwd")
                if cwd:
                    return cwd
    except OSError:
        return None
    return None


def candidate_roots(top: int = 20) -> list[dict]:
    """For each project dir, read the recorded cwd from a session and count
    sessions per cwd, ranked desc. Dedupes the multiple lossy-encoded dir-name
    variants of the same path into one real root."""
    pdir = projects_dir()
    counts: dict[str, int] = {}
    if pdir.is_dir():
        for child in pdir.iterdir():
            if not child.is_dir():
                continue
            jsonls = list(child.glob("*.jsonl"))
            if not jsonls:
                continue
            cwd = _cwd_from_session(jsonls[0])
            if not cwd or not Path(cwd).is_dir():
                continue
            counts[cwd] = counts.get(cwd, 0) + len(jsonls)
    out = [{"path": p, "session_count": n} for p, n in counts.items()]
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
