"""Minimum-confidence floor (#57): a single incidental low-weight read must
not decide a session's bucket on its own. Hand-verdicts on the golden corpus
set the policy for sub-floor evidence ("a whisper"):

- whisper agrees with the launch-dir bucket -> launch dir classifies (no change)
- whisper REFINES the launch-dir bucket (points inside a child) -> refine down
- whisper CONTRADICTS the launch-dir bucket (different branch) -> ambiguous,
  decline to needs_llm (the corpus holds confirmed sessions with this exact
  shape and OPPOSITE truths, so no deterministic answer is defensible)
- substantive evidence (any edit, or two-plus reads) decides as before

Synthetic registry only (public repo): no real client names or paths.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src' / 'pulse' / 'timecore'))
from classify import walk_registry, classify_session, classify_session_by_files

REG = {
    "buckets": [
        {"name": "alpha", "source_path": "/w/alpha",
         "children": [{"name": "deep", "source_path": "/w/alpha/deep"}]},
        {"name": "beta", "source_path": "/w/beta"},
    ],
}
FLAT = sorted(walk_registry(REG["buckets"]), key=lambda b: -b["depth"])
EXCLUDED = ["/w/scratch"]
LDE = {"/w/umbrella": ["beta"]}


def _sess(encoded="", edits=None, reads=None):
    return {"encoded": encoded, "edit_paths": edits or {}, "read_paths": reads or {}}


def test_contradicting_whisper_declines_to_llm():
    # Launch dir says beta; the only evidence is one read in alpha. The corpus
    # proves this shape is ambiguous (both truths exist) — the deterministic
    # cascade must decline rather than guess either way.
    s = _sess(encoded="-w-beta-sub", reads={"/w/alpha/x.py": 1})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason) == (None, "needs_llm")


def test_whisper_refines_launch_bucket_downward():
    # Launch dir says alpha; the one read points inside alpha's child. The
    # signals agree up to the child — refine to it.
    s = _sess(encoded="-w-alpha-sub", reads={"/w/alpha/deep/x.py": 1})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert b == ["alpha", "deep"]
    assert reason == "file_evidence_refined"


def test_whisper_agreeing_with_launch_dir_is_launch_dir():
    s = _sess(encoded="-w-alpha-sub", reads={"/w/alpha/x.py": 1})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason) == (["alpha"], "project_dir_prefix")


def test_ancestor_whisper_defers_to_deeper_launch_bucket():
    s = _sess(encoded="-w-alpha-deep-sub", reads={"/w/alpha/y.py": 1})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason) == (["alpha", "deep"], "project_dir_prefix")


def test_whisper_cannot_resurrect_excluded_launch_dir():
    s = _sess(encoded="-w-scratch-x", reads={"/w/alpha/x.py": 1})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason) == (None, "excluded")


def test_single_read_with_no_launch_match_goes_to_needs_llm():
    s = _sess(encoded="-elsewhere", reads={"/w/alpha/x.py": 1})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason) == (None, "needs_llm")


def test_two_reads_still_decide():
    s = _sess(encoded="-w-beta", reads={"/w/alpha/x.py": 2})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason) == (["alpha"], "file_evidence")


def test_two_single_reads_same_bucket_still_decide():
    s = _sess(encoded="-w-beta", reads={"/w/alpha/x.py": 1, "/w/alpha/y.py": 1})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason) == (["alpha"], "file_evidence")


def test_single_edit_still_decides():
    s = _sess(encoded="-w-beta", edits={"/w/alpha/x.py": 1})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason) == (["alpha"], "file_evidence")


def test_whisper_spread_across_buckets_falls_through():
    # One read each in two buckets from a launch dir with no prefix match:
    # every score is at the floor, none decisive — LDE fallback applies.
    s = _sess(encoded="-w-umbrella",
              reads={"/w/alpha/x.py": 1, "/w/beta/y.py": 1})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason) == (["beta"], "launch_dir_exact")


def test_by_files_itself_enforces_the_floor():
    # deploy-week imports classify_session_by_files directly — the floor must
    # live there, not only in the cascade.
    s = _sess(reads={"/w/alpha/x.py": 1})
    b, scores = classify_session_by_files(s, FLAT, EXCLUDED)
    assert (b, scores) == (None, None)
