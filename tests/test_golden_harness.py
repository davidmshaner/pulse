"""Golden-corpus harness unit tests (#58). Synthetic data only — public repo."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src' / 'pulse'))
import golden as G

REG = {
    "buckets": [
        {"name": "alpha", "source_path": "/w/alpha",
         "children": [{"name": "deep", "source_path": "/w/alpha/deep"}]},
        {"name": "beta", "source_path": "/w/beta"},
    ],
}


def _inputs(tmp_path):
    import yaml
    reg = tmp_path / "reg.yaml"
    reg.write_text(yaml.safe_dump(REG))
    return G.load_inputs(reg, tmp_path / "no-rules.yaml")


def _entry(sid="a.jsonl", status="provisional", expected=("beta",),
           encoded="", edits=None, reads=None):
    return {
        "id": sid, "status": status,
        "expected_bucket": list(expected) if expected else None,
        "evidence": {"encoded": encoded, "edit_paths": edits or {},
                     "read_paths": reads or {}},
    }


def test_load_inputs_missing_rules_ok(tmp_path):
    flat, exc, lde, valid = _inputs(tmp_path)
    assert lde == {} and ("alpha", "deep") in valid and ("beta",) in valid


def test_all_match_is_empty(tmp_path):
    flat, exc, lde, valid = _inputs(tmp_path)
    g = {"entries": [_entry(expected=("beta",), edits={"/w/beta/x": 1})]}
    assert G.compute_mismatches(g, flat, exc, lde, valid) == []


def test_provisional_and_confirmed_mismatch_kinds(tmp_path):
    flat, exc, lde, valid = _inputs(tmp_path)
    g = {"entries": [
        _entry(sid="p.jsonl", status="provisional", expected=("beta",),
               edits={"/w/alpha/x": 1}),
        _entry(sid="c.jsonl", status="confirmed", expected=("beta",),
               edits={"/w/alpha/x": 1}),
    ]}
    mm = G.compute_mismatches(g, flat, exc, lde, valid)
    kinds = {m["entry"]["id"]: m["kind"] for m in mm}
    assert kinds == {"p.jsonl": "provisional", "c.jsonl": "confirmed"}
    assert all(m["got"] == ["alpha"] for m in mm)


def test_stale_label_detected_before_replay(tmp_path):
    flat, exc, lde, valid = _inputs(tmp_path)
    g = {"entries": [_entry(expected=("gone",), edits={"/w/beta/x": 1})]}
    mm = G.compute_mismatches(g, flat, exc, lde, valid)
    assert [m["kind"] for m in mm] == ["stale"]


def test_none_expected_matches_needs_llm(tmp_path):
    flat, exc, lde, valid = _inputs(tmp_path)
    g = {"entries": [_entry(expected=None, encoded="-elsewhere")]}
    assert G.compute_mismatches(g, flat, exc, lde, valid) == []


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "golden.yaml"
    data = {"entries": [_entry()]}
    G.save_golden(p, data)
    assert G.load_golden(p) == data
    assert G.load_golden(tmp_path / "absent.yaml") == {"entries": []}
