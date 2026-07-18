"""Minimum-confidence floor (#57): a single incidental low-weight read must
not decide a session's bucket — it falls through the cascade like no evidence.

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


def test_single_read_falls_through_to_launch_dir():
    # The #55-spike mover-10 shape: a session launched in beta whose only
    # evidence is one incidental read of an alpha file.
    s = _sess(encoded="-w-beta-sub", reads={"/w/alpha/x.py": 1})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason) == (["beta"], "project_dir_prefix")


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
    # One read each in two buckets: every score is at the floor, none decisive.
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
