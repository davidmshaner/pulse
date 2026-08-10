"""config.py — single seam for machine/OS-specific paths and accounts.

Loads config.yaml from this directory and exposes resolved Path constants used
across the widget (live_bucket, snapshot, scan_cowork). No hardcoded user paths
live here — the P2 setup skill generates config.yaml per machine. Relative paths
in config.yaml resolve against the user's home; absolute paths are used as-is.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import yaml
except ImportError:
    print("MISSING_DEPS: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

PKG_DIR = Path(__file__).resolve().parent      # src/pulse — code, templates, fonts, timecore, sibling scripts
DATA_DIR = PKG_DIR.parents[1]                  # repo root — user data: config.yaml, state.json, appetite.yaml, ...
CONFIG_YAML = DATA_DIR / "config.yaml"


def _resolve(p: str) -> Path:
    """Resolve a config path against home unless already absolute."""
    path = Path(p).expanduser()
    return path if path.is_absolute() else Path.home() / path


def _load() -> dict:
    if not CONFIG_YAML.exists():
        raise FileNotFoundError(
            f"Pulse config not found: {CONFIG_YAML}. "
            "Copy examples/config.example.yaml to config.yaml (or run the Pulse setup skill)."
        )
    with open(CONFIG_YAML) as f:
        return yaml.safe_load(f) or {}


def _default_cowork_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(base) / "Claude" / "local-agent-mode-sessions"
    return Path.home() / ".config" / "Claude" / "local-agent-mode-sessions"


_cfg = _load()

LOCAL_TZ = ZoneInfo(_cfg.get("timezone", "America/New_York"))

PROJECTS_DIRS = [_resolve(p) for p in _cfg.get("projects_dirs", [".claude/projects"])]

_cr = _cfg.get("cowork_root")
COWORK_ROOT = _resolve(_cr) if _cr else _default_cowork_root()

# OpenAI Codex CLI rollout logs — Pulse's third usage surface (issue #34). Codex
# writes one JSONL "rollout" per session under ~/.codex/sessions/YYYY/MM/DD/ (and
# moves older ones to ~/.codex/archived_sessions/). Both roots are scanned so a
# recently-archived session still inside the window is not missed. Config-overridable.
_cxr = _cfg.get("codex_root")
CODEX_ROOT = _resolve(_cxr) if _cxr else Path.home() / ".codex" / "sessions"
_cxar = _cfg.get("codex_archived_root")
CODEX_ARCHIVED_ROOT = _resolve(_cxar) if _cxar else Path.home() / ".codex" / "archived_sessions"

# timecore is vendored inside this repo. Default to the package-local copy
# (clone-location independent); an explicit config value overrides it.
TIMECORE_DIR = _resolve(_cfg["timecore_dir"]) if _cfg.get("timecore_dir") else PKG_DIR / "timecore"

# Categorization inputs default to the repo-local files (standalone). An explicit
# config value (e.g. David pointing at his deploy-week context) overrides.
REGISTRY = _resolve(_cfg["registry"]) if _cfg.get("registry") else DATA_DIR / "bucket-registry.yaml"
LEARNINGS = _resolve(_cfg["learnings"]) if _cfg.get("learnings") else DATA_DIR / "learnings.yaml"
RULES = _resolve(_cfg["rules"]) if _cfg.get("rules") else DATA_DIR / "disambiguation-rules.yaml"
GOLDEN = _resolve(_cfg["golden"]) if _cfg.get("golden") else DATA_DIR / "golden-classifications.yaml"
# Per-session manual overrides (#64): a user's hand verdict on a session the
# cascade intentionally declines (whisper-ambiguous). Gitignored user data.
OVERRIDES = _resolve(_cfg["overrides"]) if _cfg.get("overrides") else DATA_DIR / "session-overrides.yaml"

_cal = _cfg.get("calendar") or {}
CALENDAR_SELF_EMAILS = list(_cal.get("self_emails", []))
# Each account: {tag, credentials_dir}. Empty = calendar off (sessions-only).
CALENDAR_ACCOUNTS = [(a["tag"], _resolve(a["credentials_dir"]))
                     for a in (_cal.get("accounts") or [])]

# --- Cowork classification (user-specific; empty by default) ----------------
# How Claude Cowork sessions map to your categories. Kept OUT of code so the
# package ships generic: a slash-command map, an email->category default, title
# regexes, and cron-template markers (sessions that are pure scheduled output).
def _compile_title_patterns(items):
    out = []
    for it in items or []:
        out.append((re.compile(it["pattern"], re.I), list(it["bucket"])))
    return out

_cw = _cfg.get("cowork_classification") or {}
COWORK_SLASH_BUCKET = {k: list(v) for k, v in (_cw.get("slash_bucket") or {}).items()}
COWORK_EMAIL_DEFAULT = {k: list(v) for k, v in (_cw.get("email_default") or {}).items()}
COWORK_TITLE_PATTERNS = _compile_title_patterns(_cw.get("title_patterns"))
# Default cron marker is the generic Claude scheduled-task envelope (not user-specific).
COWORK_CRON_TEMPLATES = [re.compile(p) for p in (_cw.get("cron_templates") or [r"^<scheduled-task"])]
