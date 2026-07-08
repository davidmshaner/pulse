"""test_launch_dir_exact.py — guards the exact launch-dir fallback.

A bare umbrella root (e.g. the monorepo root that is the parent of all buckets)
can be mapped to a bucket for sessions that have no file evidence and don't
prefix-match any source_path. The mapping must match EXACTLY — a subdirectory of
the mapped root must NOT inherit it (a prefix rule would wrongly grab every
no-file-evidence session launched anywhere under the root).
"""
import sys
from pathlib import Path

TIMECORE = Path(__file__).resolve().parent.parent / "src" / "pulse" / "timecore"
sys.path.insert(0, str(TIMECORE))

from classify import classify_session_by_launch_dir_exact  # noqa: E402

ROOT = "/Users/davidshaner/dev/chief_of_staff"
MAP = {ROOT: ["SC", "SC-internal"]}


def _sess(abs_path):
    # ~/.claude/projects encodes the abs cwd as '/' -> '-' (and '_' -> '-').
    return {"encoded": abs_path.replace("/", "-").replace("_", "-")}


def test_exact_root_resolves():
    assert classify_session_by_launch_dir_exact(_sess(ROOT), MAP) == ["SC", "SC-internal"]


def test_subdir_does_not_inherit():
    # A session launched under the mapped root must NOT match — exact only.
    assert classify_session_by_launch_dir_exact(_sess(ROOT + "/projects/offline"), MAP) is None


def test_empty_map_is_noop():
    assert classify_session_by_launch_dir_exact(_sess(ROOT), {}) is None
    assert classify_session_by_launch_dir_exact(_sess(ROOT), None) is None


def test_unrelated_dir_is_none():
    assert classify_session_by_launch_dir_exact(_sess("/Users/davidshaner/dev/other"), MAP) is None
