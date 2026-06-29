"""scan_codex.py — discover OpenAI Codex CLI sessions and normalize them into the
same shape as Claude Code CLI sessions so the existing time-accounting pipeline
works unchanged. Pulse's third usage surface, alongside scan_sessions (CLI) and
scan_cowork (Cowork) — issue #34.

Codex stores rollout logs at:
  ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl   ← live
  ~/.codex/archived_sessions/rollout-<ts>-<uuid>.jsonl     ← older, archived runs

Each rollout is JSONL. Line 0 is type 'session_meta' whose payload.cwd is the
session's working directory — the project dir, a direct bucket signal (no
path-encoding decode). Crucially, EVERY line carries a top-level UTC 'timestamp'
(ISO-8601 'Z') — the exact field time_math.collect_timestamps() reads. So a
rollout is consumed IN PLACE; no materialized copy is needed (unlike Cowork's
_audit_timestamp rewrite). A returned session dict therefore needs only
filepath + bucket_path; compute_bucket_times() does the rest.

Bucket attribution reuses the prematch path matchers
(classify_session_by_project_dir + launch_dir_exact, keyed on the encoded cwd) —
the same registry-faithful resolution CLI sessions get. Unresolved sessions are
dropped (never poison totals), consistent with scan_cowork.
"""
from __future__ import annotations

import json
import sys as _sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

WIDGET_DIR = Path(__file__).resolve().parent
_sys.path.insert(0, str(WIDGET_DIR))
_sys.path.insert(0, str(WIDGET_DIR / "timecore"))
from classify import (  # noqa: E402
    walk_registry,
    classify_session_by_project_dir,
    sc_root_to_internal,
)

# How many leading lines to scan for the session_meta envelope before giving up.
# It is line 0 in every rollout observed, but be tolerant of a stray prefix line.
_META_SCAN_LINES = 20


# --- session_meta / cwd extraction -----------------------------------------

def _session_meta(filepath: Path) -> dict | None:
    """Return the payload of the first 'session_meta' line of a rollout, or None.
    The payload carries cwd, id, originator, and optional source.subagent."""
    try:
        with open(filepath) as f:
            for _ in range(_META_SCAN_LINES):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("type") == "session_meta":
                    return e.get("payload") or {}
    except OSError:
        return None
    return None


# --- bucket resolution (reuse the registry classifiers) --------------------

def _resolve_bucket(cwd: str, flat_buckets_sorted, excluded_paths) -> list | None:
    """Resolve a Codex cwd to a bucket path via the same project-dir matcher
    prematch uses for CLI sessions. Returns the bucket path (list) or None (drop).

    Codex has no path-encoded project dir like ~/.claude/projects, so we synthesize
    the `encoded` form the matcher expects ('/'->'-', '_'->'-')."""
    if not cwd:
        return None
    sess = {"encoded": cwd.replace("/", "-").replace("_", "-")}
    b, _reason = classify_session_by_project_dir(sess, flat_buckets_sorted, excluded_paths)
    if b:
        return sc_root_to_internal(b)
    return None


# --- discovery -------------------------------------------------------------

def _iter_rollout_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        yield from root.rglob("rollout-*.jsonl")


# --- public API ------------------------------------------------------------

def scan(window_start: datetime, window_end: datetime,
         roots: list[Path] | None = None,
         registry: dict | None = None) -> list[dict]:
    """Walk Codex rollouts, window-prefilter by mtime, resolve a bucket from cwd,
    and return CLI-shape session dicts compatible with the existing pipeline.

    Shape: {filepath, bucket_path, first_ts, last_ts, encoded, category}. Only
    filepath + bucket_path are consumed by compute_bucket_times; the rest are for
    parity/diagnostics. `roots`/`registry` default to config (injectable for
    tests). Reading is in place — the rollout's own top-level timestamps are
    re-read per-line by compute_bucket_times within the exact window."""
    if roots is None or registry is None:
        import yaml  # local import: only needed when loading config files
        _sys.path.insert(0, str(WIDGET_DIR))
        import config  # noqa: E402
        if roots is None:
            roots = [config.CODEX_ROOT, config.CODEX_ARCHIVED_ROOT]
        if registry is None:
            with open(config.REGISTRY) as f:
                registry = yaml.safe_load(f) or {}

    flat = sorted(walk_registry(registry.get("buckets", [])), key=lambda b: -b["depth"])
    excluded_paths = registry.get("exclude_paths") or []

    window_start_epoch = window_start.timestamp()

    sessions: list[dict] = []
    for path in _iter_rollout_files(roots):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        # Cheap candidate filter: a session whose last activity is before the
        # window can't contribute. compute_bucket_times re-clips per line, so this
        # only prunes obviously-stale files (epoch compare is tz-agnostic).
        if mtime < window_start_epoch:
            continue
        meta = _session_meta(path)
        if not meta:
            continue
        bucket = _resolve_bucket(meta.get("cwd", ""), flat, excluded_paths)
        if bucket is None:
            continue  # unresolvable cwd — drop rather than poison totals
        sessions.append({
            "filepath":    str(path),
            "bucket_path": bucket,
            "first_ts":    None,
            "last_ts":     None,
            "encoded":     meta.get("cwd", "").replace("/", "-").replace("_", "-"),
            "category":    "codex",
        })
    return sessions


if __name__ == "__main__":
    # Diagnostic: scan last 7d and print a summary.
    from datetime import timedelta, timezone
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    out = scan(start, end)
    print(f"found {len(out)} Codex sessions in last 7d")
    for s in out:
        print(f"  bucket={'.'.join(s['bucket_path']):20}  {s['filepath']}")
