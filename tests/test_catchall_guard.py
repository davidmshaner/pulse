"""P3refined guardrail (#55): a bucket claim that is exactly a catch-all global
dir (~/.claude/skills, ~/.claude/projects) is not file evidence — every session
touches those dirs as a side effect, so such a claim can silently reroute other
ventures' sessions. Deeper, specific claims still count.

Synthetic registry only (public repo); the catch-all paths are built from
Path.home() so the tests are portable.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src' / 'pulse' / 'timecore'))
from pathlib import Path

from classify import (
    walk_registry,
    match_file_to_bucket,
    classify_session_by_files,
    classify_session,
    catchall_claims,
)

HOME = str(Path.home())
REG = {
    "buckets": [
        {"name": "internal", "source_path": "/w/internal",
         "additional_paths": [f"{HOME}/.claude/skills", f"{HOME}/.claude/projects"]},
        {"name": "tools", "source_path": f"{HOME}/.claude/skills/deploy-week"},
        {"name": "beta", "source_path": "/w/beta"},
    ],
}
FLAT = sorted(walk_registry(REG["buckets"]), key=lambda b: -b["depth"])


def _sess(encoded="", edits=None, reads=None):
    return {"encoded": encoded, "edit_paths": edits or {}, "read_paths": reads or {}}


def test_matcher_skips_exact_catchall_claim():
    assert match_file_to_bucket(f"{HOME}/.claude/skills/some-skill/SKILL.md", FLAT, []) is None
    assert match_file_to_bucket(f"{HOME}/.claude/projects/-w-elsewhere/memory/x.md", FLAT, []) is None


def test_deeper_specific_claim_still_counts():
    b = match_file_to_bucket(f"{HOME}/.claude/skills/deploy-week/SKILL.md", FLAT, [])
    assert b == ("tools",)


def test_skill_reads_alone_no_longer_produce_evidence():
    s = _sess(reads={f"{HOME}/.claude/skills/some-skill/SKILL.md": 51})
    b, scores = classify_session_by_files(s, FLAT, [])
    assert b is None and scores is None


def test_poisoned_session_falls_back_to_launch_dir():
    # The #55 shape: launched in venture beta's dir, ONLY file traffic is
    # skill reads — previously classified to `internal` via the catch-all,
    # must now resolve to beta via project_dir_prefix.
    s = _sess(encoded="-w-beta-sub",
              reads={f"{HOME}/.claude/skills/some-skill/SKILL.md": 12})
    b, reason, scores = classify_session(s, FLAT, [], {})
    assert (b, reason) == (["beta"], "project_dir_prefix")


def test_non_catchall_claims_unaffected():
    s = _sess(edits={"/w/internal/notes.md": 1})
    b, scores = classify_session_by_files(s, FLAT, [])
    assert b == ["internal"]


def test_catchall_claims_flags_offending_buckets():
    got = {(path, src) for path, src in catchall_claims(FLAT)}
    assert got == {
        (("internal",), f"{HOME}/.claude/skills"),
        (("internal",), f"{HOME}/.claude/projects"),
    }


def test_catchall_claims_ignores_deep_and_normal_claims():
    flat = sorted(walk_registry(
        {"buckets": [{"name": "tools", "source_path": f"{HOME}/.claude/skills/deploy-week"},
                     {"name": "beta", "source_path": "/w/beta"}]}["buckets"]
    ), key=lambda b: -b["depth"])
    assert catchall_claims(flat) == []


def test_tilde_form_catchall_also_flagged_and_skipped():
    reg = {"buckets": [{"name": "internal", "source_path": "/w/internal",
                        "additional_paths": ["~/.claude/skills"]}]}
    flat = sorted(walk_registry(reg["buckets"]), key=lambda b: -b["depth"])
    assert catchall_claims(flat) == [(("internal",), "~/.claude/skills")]


def test_prematch_warns_on_catchall_claims():
    import io, pathlib, sys as _s
    _s.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src' / 'pulse'))
    import prematch
    buf = io.StringIO()
    prematch.warn_catchall_claims(FLAT, out=buf)
    msg = buf.getvalue()
    assert "internal" in msg and ".claude/skills" in msg and ".claude/projects" in msg
    assert "#55" in msg
    buf2 = io.StringIO()
    prematch.warn_catchall_claims([], out=buf2)
    assert buf2.getvalue() == ""
