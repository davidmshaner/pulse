"""classify_session() — the extracted session cascade (#58).

Synthetic registry only (public repo): no real client names or paths.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src' / 'pulse' / 'timecore'))
from classify import walk_registry, classify_session

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


def test_file_evidence_wins_over_launch_dir():
    s = _sess(encoded="-w-beta", edits={"/w/alpha/deep/x.py": 2})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert b == ["alpha", "deep"]
    assert reason == "file_evidence"
    assert scores == {"('alpha', 'deep')": 2.0}


def test_read_weight_is_fifth_of_edit():
    s = _sess(edits={"/w/beta/a.py": 1}, reads={"/w/alpha/b.py": 4})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert b == ["beta"]          # 1.0 edit beats 4*0.2=0.8 reads
    assert reason == "file_evidence"


def test_project_dir_prefix_fallback():
    s = _sess(encoded="-w-alpha-deep-sub")
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason, scores) == (["alpha", "deep"], "project_dir_prefix", {})


def test_excluded_launch_dir():
    s = _sess(encoded="-w-scratch-x")
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason) == (None, "excluded")


def test_launch_dir_exact_fallback():
    s = _sess(encoded="-w-umbrella")
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason, scores) == (["beta"], "launch_dir_exact", {})


def test_needs_llm_when_nothing_matches():
    s = _sess(encoded="-elsewhere", reads={"/nowhere/x": 1})
    b, reason, scores = classify_session(s, FLAT, EXCLUDED, LDE)
    assert (b, reason, scores) == (None, "needs_llm", {})
