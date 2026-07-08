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

ROOT = "/Users/u/dev/monorepo_root"
MAP = {ROOT: ["umbrella", "umbrella-internal"]}


def _sess(abs_path):
    # ~/.claude/projects encodes the abs cwd: '/', '_', and '.' all become '-'.
    return {"encoded": abs_path.replace("/", "-").replace("_", "-").replace(".", "-")}


def test_exact_root_resolves():
    assert classify_session_by_launch_dir_exact(_sess(ROOT), MAP) == [
        "umbrella", "umbrella-internal"]


def test_subdir_does_not_inherit():
    # A session launched under the mapped root must NOT match — exact only.
    assert classify_session_by_launch_dir_exact(
        _sess(ROOT + "/projects/sub"), MAP) is None


def test_empty_map_is_noop():
    assert classify_session_by_launch_dir_exact(_sess(ROOT), {}) is None
    assert classify_session_by_launch_dir_exact(_sess(ROOT), None) is None


def test_unrelated_dir_is_none():
    assert classify_session_by_launch_dir_exact(_sess("/Users/u/dev/other"), MAP) is None


def test_dotted_path_matches():
    # Claude Code encodes '.' to '-' in project dir names (e.g. 'site.com' ->
    # 'site-com'); the rule path must be normalized the same way or dotted
    # dirs silently never match.
    m = {"/Users/u/dev/site.com": ["personal", "site"]}
    assert classify_session_by_launch_dir_exact(
        _sess("/Users/u/dev/site.com"), m) == ["personal", "site"]


def test_old_style_underscore_encoding_matches():
    # Older ~/.claude/projects dirs preserve '_' (monorepo_root stays
    # monorepo_root, not monorepo-root); the session side must be normalized
    # too or the feature's own motivating case leaks to needs_llm.
    old = {"encoded": "-Users-u-dev-monorepo_root"}
    assert classify_session_by_launch_dir_exact(old, MAP) == [
        "umbrella", "umbrella-internal"]


def test_string_bucket_and_trailing_slash():
    # A hand-edited YAML may give a bare string bucket (must not char-split
    # into ['S','C',...]) or a trailing-slash path (must still match).
    m = {ROOT + "/": "umbrella"}
    assert classify_session_by_launch_dir_exact(_sess(ROOT), m) == ["umbrella"]
