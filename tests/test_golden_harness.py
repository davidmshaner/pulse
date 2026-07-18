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


def test_stale_label_detected(tmp_path):
    flat, exc, lde, valid = _inputs(tmp_path)
    g = {"entries": [_entry(expected=("gone",), edits={"/w/beta/x": 1})]}
    mm = G.compute_mismatches(g, flat, exc, lde, valid)
    assert [m["kind"] for m in mm] == ["stale"]


def test_stale_mismatch_carries_replayed_bucket(tmp_path):
    flat, exc, lde, valid = _inputs(tmp_path)
    g = {"entries": [_entry(expected=("gone",), edits={"/w/beta/x": 1})]}
    mm = G.compute_mismatches(g, flat, exc, lde, valid)
    assert mm[0]["kind"] == "stale" and mm[0]["got"] == ["beta"]


def test_none_expected_matches_needs_llm(tmp_path):
    flat, exc, lde, valid = _inputs(tmp_path)
    g = {"entries": [_entry(expected=None, encoded="-elsewhere")]}
    assert G.compute_mismatches(g, flat, exc, lde, valid) == []


def test_none_expected_flags_mismatch_when_replay_finds_bucket(tmp_path):
    flat, exc, lde, valid = _inputs(tmp_path)
    g = {"entries": [_entry(expected=None, edits={"/w/beta/x": 1})]}
    mm = G.compute_mismatches(g, flat, exc, lde, valid)
    assert len(mm) == 1 and mm[0]["got"] == ["beta"] and mm[0]["kind"] == "provisional"


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "golden.yaml"
    data = {"entries": [_entry()]}
    G.save_golden(p, data)
    assert G.load_golden(p) == data
    assert G.load_golden(tmp_path / "absent.yaml") == {"entries": []}


def test_load_golden_normalizes_bare_entries_key(tmp_path):
    p = tmp_path / "golden.yaml"
    p.write_text("entries:\n")
    assert G.load_golden(p) == {"entries": []}


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


def test_format_failures_groups_and_points_to_review(tmp_path):
    flat, exc, lde, valid = _inputs(tmp_path)
    g = {"entries": [
        _entry(sid="c.jsonl", status="confirmed", expected=("beta",), edits={"/w/alpha/x": 1}),
        _entry(sid="p.jsonl", status="provisional", expected=("beta",), edits={"/w/alpha/x": 1}),
        _entry(sid="st.jsonl", expected=("gone",)),
    ]}
    msg = G.format_failures(G.compute_mismatches(g, flat, exc, lde, valid))
    assert "REGRESSION against hand-validated truth" in msg
    assert "c.jsonl: ['beta'] -> ['alpha'] (file_evidence)" in msg
    assert "unreviewed mover" in msg and "p.jsonl" in msg
    assert "python3 src/pulse/golden.py review" in msg
    assert "stale label" in msg and "st.jsonl" in msg


def test_apply_verdict_new_rebaselines_and_confirms():
    e = _entry(status="provisional", expected=("beta",))
    assert G.apply_verdict(e, ["alpha"], "new", today="2026-07-17")
    assert e["expected_bucket"] == ["alpha"]
    assert e["status"] == "confirmed" and e["labeled_at"] == "2026-07-17"


def test_apply_verdict_old_pins_and_confirms():
    e = _entry(status="provisional", expected=("beta",))
    assert G.apply_verdict(e, ["alpha"], "old", today="2026-07-17")
    assert e["expected_bucket"] == ["beta"]      # unchanged
    assert e["status"] == "confirmed"


def test_apply_verdict_new_accepts_none_bucket():
    e = _entry(status="provisional", expected=("beta",))
    assert G.apply_verdict(e, None, "new", today="2026-07-17")
    assert e["expected_bucket"] is None


def test_apply_verdict_skip_changes_nothing():
    e = _entry(status="provisional", expected=("beta",))
    assert not G.apply_verdict(e, ["alpha"], "skip")
    assert e["status"] == "provisional" and "labeled_at" not in e
