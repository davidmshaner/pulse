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

Bucket attribution: Codex's cwd is a real absolute path, so we resolve it with
the shared match_file_to_bucket() — exact path-prefix matching, the same matcher
CLI file-evidence uses. (We deliberately do NOT round-trip through the
~/.claude-style "encoded" form + encoded_matches, whose '-'-delimited prefix test
would mis-resolve a sibling dir like /x/acme-archive onto the /x/acme bucket.)

Codex Desktop runs every session inside an ephemeral git worktree under
~/.codex/worktrees/<hash>/<repo-leaf> — a cwd that matches no registry bucket. We
map it back to its origin repo via the worktree's .git gitdir before resolving
(see _effective_project_dir), so Desktop work is attributed to the real project.
A worktree Codex has already deleted can't be resolved from its path and is
counted as unresolved (logged), not guessed.

Scope, vs the richer CLI path: CLI sessions resolve by file-evidence first, then
project-dir, then escalate to needs_llm. Codex here resolves by (worktree-aware)
cwd only and drops anything unresolved (never poisons totals, consistent with
scan_cowork). file-evidence / needs_llm escalation is a future follow-up.
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
    match_file_to_bucket,
    sc_root_to_internal,
)

# How many leading lines to scan for the session_meta envelope before giving up.
# It is line 0 in every rollout observed, but be tolerant of a stray prefix line.
_META_SCAN_LINES = 20


# --- session_meta / cwd extraction -----------------------------------------

def _session_meta(filepath: Path) -> dict | None:
    """Return the payload of the first 'session_meta' line of a rollout, or None.
    The payload carries cwd, id, originator, and optional source.subagent.

    Tolerant like time_math.collect_timestamps: a partially-written or non-UTF-8
    rollout (Codex may be mid-write) must skip that one file, never crash the whole
    snapshot refresh — so catch UnicodeDecodeError (from readline), not just OSError."""
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
    except (OSError, UnicodeDecodeError):
        return None
    return None


# --- worktree → origin repo resolution -------------------------------------

# Codex Desktop runs every session inside an ephemeral git worktree under
# ~/.codex/worktrees/<hash>/<repo-leaf>. That cwd matches no registry source_path,
# so without this step ALL Codex Desktop work is dropped. The worktree's .git file
# records "gitdir: <origin-repo>/.git/worktrees/<name>" — the only exact origin
# signal, valid while the worktree exists on disk.
_CODEX_WORKTREE_MARKER = "/.codex/worktrees/"
_GIT_WORKTREE_MARKER = "/.git/worktrees/"


def _effective_project_dir(cwd: str) -> str | None:
    """Map a Codex cwd to the real project dir for bucket resolution.

    - Not a Codex worktree → return cwd unchanged.
    - A worktree we can resolve (its .git gitdir is readable) → the origin repo.
    - A worktree we can't resolve (already deleted — the path alone can't tell us
      which repo it was) → None, so the caller counts it as an unresolved worktree
      rather than guessing and risking misattribution of billable hours."""
    if _CODEX_WORKTREE_MARKER not in cwd:
        return cwd
    try:
        txt = (Path(cwd) / ".git").read_text()
    except OSError:
        return None
    for line in txt.splitlines():
        if line.startswith("gitdir:") and _GIT_WORKTREE_MARKER in line:
            return line.split("gitdir:", 1)[1].strip().split(_GIT_WORKTREE_MARKER)[0]
    return None


# --- bucket resolution (reuse the registry classifiers) --------------------

def _resolve_bucket(cwd: str, flat_buckets_sorted, excluded_paths) -> list | None:
    """Resolve a Codex cwd to a bucket path. Returns the bucket path (list) or None.

    Codex's cwd is a real absolute path, so match it EXACTLY with the shared
    match_file_to_bucket (fp == src or fp.startswith(src + '/'), and excluded_paths
    rejected first). Using the real path avoids the false positives the lossy
    encoded-form matcher produces — e.g. /x/acme-archive must NOT land on /x/acme."""
    if not cwd:
        return None
    b = match_file_to_bucket(cwd, flat_buckets_sorted, excluded_paths)
    return sc_root_to_internal(list(b)) if b else None


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
        import config  # noqa: E402  (WIDGET_DIR already on sys.path from module import)
        if roots is None:
            roots = [config.CODEX_ROOT, config.CODEX_ARCHIVED_ROOT]
        if registry is None:
            with open(config.REGISTRY) as f:
                registry = yaml.safe_load(f) or {}

    flat = sorted(walk_registry(registry.get("buckets", [])), key=lambda b: -b["depth"])
    excluded_paths = registry.get("exclude_paths") or []

    window_start_epoch = window_start.timestamp()

    sessions: list[dict] = []
    unresolved_worktrees = 0
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
        cwd = meta.get("cwd", "")
        proj = _effective_project_dir(cwd)
        if proj is None:
            unresolved_worktrees += 1  # Codex worktree already deleted — can't attribute
            continue
        bucket = _resolve_bucket(proj, flat, excluded_paths)
        if bucket is None:
            continue  # cwd not under any registry bucket (or excluded) — drop, don't poison totals
        sessions.append({
            "filepath":    str(path),
            "bucket_path": bucket,
            "first_ts":    None,
            "last_ts":     None,
            "encoded":     proj,         # diagnostic only; pipeline reads filepath + bucket_path
            "category":    "codex",
        })
    if unresolved_worktrees:
        print(f"scan_codex: {unresolved_worktrees} Codex worktree session(s) "
              f"unresolved (worktree deleted)", file=_sys.stderr)
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
