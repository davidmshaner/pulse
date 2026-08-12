#!/usr/bin/env python3
"""live_bucket.py — current bucket detector.

Finds the JSONL with the most recent line write within the last N minutes,
maps its encoded project_dir to a bucket path via prematch's registry walker.

Returns None if no session has been turn-active in the window. The widget's
title-painting logic uses None to fall back to "worst offender / all ok".
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import yaml

WIDGET_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(WIDGET_DIR))
import config  # noqa: E402

REGISTRY = config.REGISTRY
PROJECTS_DIRS = config.PROJECTS_DIRS

sys.path.insert(0, str(config.TIMECORE_DIR))
from classify import (  # noqa: E402  timecore primitives (was deploy-week prematch facade)
    walk_registry,
    classify_session_by_project_dir,
    sc_root_to_internal,
)

DEFAULT_WINDOW_MIN = 5


def find_recent_jsonl(window_min: int = DEFAULT_WINDOW_MIN) -> Path | None:
    """Most recently modified JSONL across the projects dirs, if within window.

    Skips dotfile dirs and anything not ending in .jsonl. Returns None if
    nothing has been written in the window.
    """
    cutoff = time.time() - window_min * 60
    best: Path | None = None
    best_mtime = 0.0
    for root in PROJECTS_DIRS:
        if not root.exists():
            continue
        for p in root.rglob("*.jsonl"):
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if mtime > best_mtime:
                best_mtime = mtime
                best = p
    if best is None or best_mtime < cutoff:
        return None
    return best


def read_session_cwd(jsonl: Path, max_lines: int = 20) -> str | None:
    """First non-sidechain cwd in the session JSONL head (#71) — the raw launch
    dir the encoded parent-dir name lossily encodes. Fail-silent: any read/parse
    problem returns None and the caller falls back to encoded matching."""
    try:
        with open(jsonl) as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("cwd") and not e.get("isSidechain"):
                    return e["cwd"]
    except Exception:
        return None
    return None


def resolve_bucket(encoded: str, cwd: str | None = None) -> list[str] | None:
    """Map a session's launch dir to a bucket path. Prefers the raw cwd (#71:
    real-path matching, worktree-normalized) over the lossy encoded dir name."""
    with open(REGISTRY) as f:
        registry = yaml.safe_load(f)
    flat = sorted(walk_registry(registry["buckets"]), key=lambda b: -b["depth"])
    excluded = registry.get("exclude_paths") or []
    sess = {"encoded": encoded, "cwd": cwd}
    bp, _ = classify_session_by_project_dir(sess, flat, excluded)
    if bp is None:
        return None
    return sc_root_to_internal(bp)


def detect(window_min: int = DEFAULT_WINDOW_MIN) -> dict | None:
    jsonl = find_recent_jsonl(window_min)
    if jsonl is None:
        return None
    encoded = jsonl.parent.name
    bp = resolve_bucket(encoded, cwd=read_session_cwd(jsonl))
    minutes_ago = (time.time() - jsonl.stat().st_mtime) / 60
    return {
        "bucket_path": bp,
        "last_active_minutes_ago": round(minutes_ago, 1),
        "encoded": encoded,
        "jsonl": str(jsonl),
    }


def main() -> None:
    result = detect()
    print(json.dumps({"live_bucket": result}, indent=2))


if __name__ == "__main__":
    main()
