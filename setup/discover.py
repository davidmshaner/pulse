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


# --- calendar credential discovery (optional) ------------------------------
# Pulse reuses existing Google OAuth credential files rather than running its own
# login: fetch_meetings.load_creds accepts any *.json in a dir that carries a
# 'token' or 'refresh_token' key. Detection is by that SHAPE, not by directory
# name, so it finds both the standard google_workspace_mcp layout and hand-rolled
# setups in custom locations. It reads only key presence — never token VALUES —
# and returns paths + tags (privacy, see process/conventions.md #8).

DEFAULT_CRED_ROOTS = [Path.home() / ".google_workspace_mcp"]


def _has_cred_file(d: Path) -> bool:
    """True if dir d holds a *.json with a Google OAuth token shape. Mirrors
    fetch_meetings.load_creds' acceptance rule exactly (same glob + 'token' or
    'refresh_token' key) so a dir discovery accepts is one the fetcher will load;
    test_cred_shape_agreement pins the two together. Expands '~' so a user-typed
    hand-rolled path validates (config._resolve expands it at runtime too)."""
    try:
        d = Path(d).expanduser()
        if not d.is_dir():
            return False
        for p in d.glob("*.json"):
            try:
                with open(p) as f:
                    data = json.load(f)
            except Exception:
                continue
            if isinstance(data, dict) and ("token" in data or "refresh_token" in data):
                return True
    except OSError:
        return False
    return False


def validate_cred_dir(path) -> bool:
    """Whether a (possibly hand-rolled) credential dir holds a usable Google cred
    file. Use to validate a path a user points at when auto-discovery found none."""
    return _has_cred_file(Path(path))


def _tag_for(dir_name: str) -> str:
    if dir_name.startswith("credentials_"):
        stripped = dir_name[len("credentials_"):]
        return stripped or dir_name  # don't yield an empty tag for a bare 'credentials_'
    return dir_name


def cred_dir_candidates(search_roots=None) -> list[dict]:
    """Calendar credential dirs found by shape under each search root (the root
    itself and its immediate subdirs). Returns [{tag, credentials_dir}] — paths
    only, no secrets. Empty does NOT mean the user has none: the setup skill asks
    for a hand-rolled path (validated via validate_cred_dir) before assuming so."""
    if search_roots is None:
        search_roots = DEFAULT_CRED_ROOTS
    seen, out = set(), []  # seen dedupes in case search_roots overlap
    for root in search_roots:
        root = Path(root).expanduser()
        dirs = [root]
        try:
            if root.is_dir():
                dirs += [c for c in sorted(root.iterdir()) if c.is_dir()]
        except OSError:
            pass
        for d in dirs:
            if d in seen:
                continue
            seen.add(d)
            if _has_cred_file(d):
                out.append({"tag": _tag_for(d.name), "credentials_dir": str(d)})
    return out


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
        "calendar_cred_candidates": cred_dir_candidates(),
    }


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
