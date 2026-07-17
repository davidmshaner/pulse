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


def _fake_prematch(tmp_path, sessions):
    import json
    p = tmp_path / "prematch.json"
    p.write_text(json.dumps({"confident": {"sessions": sessions}}))
    return p


def _pm_sess(name="s1.jsonl", bucket=("beta",)):
    return {"filepath": f"/logs/{name}", "bucket_path": list(bucket),
            "encoded": "-w-beta", "edit_paths": {"/w/beta/x": 1},
            "read_paths": {}, "text_blob": "SECRET", "first_msg": "SECRET",
            "bash_commands": ["SECRET"]}


def test_seed_appends_provisional_and_strips_text(tmp_path):
    gp = tmp_path / "golden.yaml"
    pm = _fake_prematch(tmp_path, [_pm_sess()])
    assert G.seed(pm, gp) == 1
    data = G.load_golden(gp)
    e = data["entries"][0]
    assert e["id"] == "s1.jsonl" and e["status"] == "provisional"
    assert e["expected_bucket"] == ["beta"]
    assert "SECRET" not in gp.read_text()


def test_seed_idempotent_and_preserves_confirmed(tmp_path):
    gp = tmp_path / "golden.yaml"
    confirmed = _entry(sid="s1.jsonl", status="confirmed", expected=("alpha",))
    G.save_golden(gp, {"entries": [confirmed]})
    pm = _fake_prematch(tmp_path, [_pm_sess(name="s1.jsonl"), _pm_sess(name="s2.jsonl")])
    assert G.seed(pm, gp) == 1          # only s2 is new
    assert G.seed(pm, gp) == 0          # idempotent
    data = G.load_golden(gp)
    by_id = {e["id"]: e for e in data["entries"]}
    assert by_id["s1.jsonl"]["status"] == "confirmed"          # untouched
    assert by_id["s1.jsonl"]["expected_bucket"] == ["alpha"]   # untouched
    assert by_id["s2.jsonl"]["status"] == "provisional"
