# Classification Golden Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A hand-validated golden corpus + replay gate (#58) so any classifier heuristic change surfaces exactly which past sessions would re-bucket and forces a human verdict before merge.

**Architecture:** Extract the session cascade from `prematch.py` into a pure `classify_session()` in `timecore/classify.py`; a new `golden.py` module replays frozen evidence snapshots (`golden-classifications.yaml`, gitignored) through that same cascade against the live registry/rules. A pytest gate fails on mismatches; a CLI (`seed`/`review`/`status`) handles the interactive labeling. Spec (the contract): `docs/specs/2026-07-17-classification-golden-corpus-design.md`.

**Tech Stack:** Python 3 (stdlib + pyyaml, already required). No new deps.

## Global Constraints

- Repo is PUBLIC. `golden-classifications.yaml` must be gitignored; committed tests use synthetic registries/paths only (pattern: `tests/test_soft_resolve.py` uses `globex.com`/`acme.com`). Never commit real client names or David's absolute paths.
- The golden file stores only paths + counts — never `text_blob`, `first_msg`, or `bash_commands`.
- Tests import by `sys.path.insert` of `src/pulse` (see any existing test); there is no package install. CLIs run by path: `python3 src/pulse/golden.py <cmd>`.
- Run tests from the worktree root: `python3 -m pytest -q` must stay green after every task.
- Behavior-preservation: the `classify_session()` extraction must produce byte-identical `prematch.json` output over the current corpus (verified in Task 1 and again in Task 7).
- Only the bucket is asserted by the gate; `reason`/scores are diagnostics.
- Vendored-copy rule: `src/pulse/timecore/classify.py` changes are mirrored to the canonical copy at `<monorepo>/.claude/skills/code-blocks/blocks/timecore/classify.py` (Task 6; separate monorepo commit, not part of the Pulse PR).

## File Structure

- `src/pulse/timecore/classify.py` — add `classify_session()` (the cascade; single source of truth).
- `src/pulse/prematch.py` — session loop delegates to `classify_session()`.
- `src/pulse/golden.py` — NEW: load/save, replay, `compute_mismatches`, `seed`, `apply_verdict`, `review`, `status`, `format_failures`, argparse main.
- `src/pulse/config.py` — add `GOLDEN`.
- `.gitignore` — add `golden-classifications.yaml`.
- `tests/test_classify_session.py` — NEW: cascade unit tests (synthetic registry).
- `tests/test_golden_harness.py` — NEW: mismatch/seed/verdict/format unit tests.
- `tests/test_golden_classifications.py` — NEW: the gate itself.
- `tests/test_timecore_sync.py` — NEW: canonical/vendored byte-identity (skips when canonical absent).

---

### Task 1: Extract `classify_session()` and refactor `prematch.py`

**Files:**
- Modify: `src/pulse/timecore/classify.py` (append after `sc_root_to_internal`)
- Modify: `src/pulse/prematch.py` (imports + session loop in `main()`)
- Test: `tests/test_classify_session.py`

**Interfaces:**
- Produces: `classify_session(sess: dict, flat_buckets_sorted: list, excluded_paths: list, launch_dir_exact: dict) -> (bucket_path: list|None, reason: str, evidence_scores: dict)`. `reason` ∈ {`file_evidence`, `project_dir_prefix`, `launch_dir_exact`, `excluded`, `needs_llm`}. `bucket_path` is post-`sc_root_to_internal`. `evidence_scores` is `{str(bucket_tuple): float}` for `file_evidence`, else `{}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_classify_session.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_classify_session.py -q`
Expected: ImportError — `cannot import name 'classify_session'`.

- [ ] **Step 3: Implement `classify_session()`**

Append to `src/pulse/timecore/classify.py` (after `sc_root_to_internal`):

```python
def classify_session(sess, flat_buckets_sorted, excluded_paths, launch_dir_exact):
    """The full session cascade, in shipping order: file_evidence ->
    project_dir_prefix -> launch_dir_exact -> needs_llm. Single source of
    truth shared by prematch.py and the golden-corpus replay (#58): a session
    is classified identically no matter which consumer asks.

    Returns (bucket_path|None, reason, evidence_scores). bucket_path is
    post-ROOT_REDIRECT. reason "excluded" means the launch dir is registry-
    excluded (callers drop the session entirely)."""
    b, scores = classify_session_by_files(sess, flat_buckets_sorted, excluded_paths)
    if b:
        return sc_root_to_internal(b), "file_evidence", scores
    b, reason = classify_session_by_project_dir(sess, flat_buckets_sorted, excluded_paths)
    if b:
        return sc_root_to_internal(b), reason, {}
    if reason == "excluded":
        return None, "excluded", {}
    b = classify_session_by_launch_dir_exact(sess, launch_dir_exact)
    if b:
        return sc_root_to_internal(b), "launch_dir_exact", {}
    return None, "needs_llm", {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_classify_session.py -q`
Expected: 6 passed.

- [ ] **Step 5: Refactor `prematch.py` to call it**

In `src/pulse/prematch.py`, add `classify_session` to the `from classify import (...)` list. Replace the whole session loop body (the `for s in sessions_data.get("sessions", []):` block) with:

```python
    for s in sessions_data.get("sessions", []):
        if s.get("category") != "interactive":
            continue
        b, reason, scores = classify_session(s, flat_buckets_sorted, excluded_paths, launch_dir_exact)
        if reason == "excluded":
            continue
        s["bucket_path"] = b
        s["reason"] = reason
        s["evidence_scores"] = scores
        (sess_confident if b else sess_needs_llm).append(s)
```

Note: this intentionally reproduces the original behavior exactly, including `reason: "needs_llm"` + `bucket_path: None` on the fall-through.

- [ ] **Step 6: Full suite + behavior-preservation check**

Run: `python3 -m pytest -q` — expected: all green.
Then verify 0 movers against the shipped cache (real data lives in the MAIN checkout, not the worktree — read-only, nothing written):

```bash
python3 - << 'EOF'
import json, sys
from pathlib import Path
ROOT = Path.cwd().resolve().parents[1]  # .worktrees/issue-58 -> pulse main checkout
sys.path.insert(0, "src/pulse"); sys.path.insert(0, "src/pulse/timecore")
import yaml
from classify import walk_registry, classify_session
reg = yaml.safe_load(open(ROOT / "bucket-registry.yaml"))
rules = yaml.safe_load(open(ROOT / "disambiguation-rules.yaml")) or {}
flat = sorted(walk_registry(reg["buckets"]), key=lambda b: -b["depth"])
exc = reg.get("exclude_paths") or []
lde = rules.get("session_launch_dir_exact") or {}
pm = json.load(open(ROOT / ".cache" / "prematch.json"))
movers = 0
for s in pm["confident"]["sessions"]:
    b, reason, _ = classify_session(s, flat, exc, lde)
    if b != s["bucket_path"]:
        movers += 1
        print("MOVER", Path(s["filepath"]).name, s["bucket_path"], "->", b)
print("movers:", movers)
EOF
```

Expected: `movers: 0`. If nonzero, the extraction changed behavior — STOP and fix before continuing.

- [ ] **Step 7: Commit**

```bash
git add src/pulse/timecore/classify.py src/pulse/prematch.py tests/test_classify_session.py
git commit -m "refactor(classify): extract classify_session() cascade shared by prematch + golden replay (#58)"
```

---

### Task 2: `golden.py` core — schema, replay, mismatch computation

**Files:**
- Create: `src/pulse/golden.py`
- Modify: `src/pulse/config.py` (after the `RULES` line)
- Modify: `.gitignore` (after `disambiguation-rules.yaml`)
- Test: `tests/test_golden_harness.py`

**Interfaces:**
- Consumes: `classify_session()` from Task 1.
- Produces (used by Tasks 3-5):
  - `load_golden(path) -> {"entries": [...]}` / `save_golden(path, data)` (atomic tmp+rename)
  - `load_inputs(registry_path, rules_path) -> (flat_buckets_sorted, excluded_paths, launch_dir_exact, valid_buckets: set[tuple])`
  - `compute_mismatches(golden, flat, excluded, lde, valid_buckets) -> [ {entry, kind: "confirmed"|"provisional"|"stale", got: list|None, reason: str|None, scores: dict} ]`
  - `config.GOLDEN: Path`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_golden_harness.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_golden_harness.py -q`
Expected: ImportError — no module named `golden`.

- [ ] **Step 3: Implement `golden.py` core**

Create `src/pulse/golden.py`:

```python
#!/usr/bin/env python3
"""golden.py — classification golden corpus (#58).

A gitignored, hand-validated set of frozen session-evidence snapshots
(golden-classifications.yaml) replayed through the shipping cascade
(timecore.classify.classify_session) against the LIVE registry + rules.
The pytest gate (tests/test_golden_classifications.py) fails when any entry's
replayed bucket differs from its expected bucket; this CLI does the human side:

  python3 src/pulse/golden.py seed     # import current confident sessions as provisional
  python3 src/pulse/golden.py review   # rule on mismatches (new-right / old-right / skip)
  python3 src/pulse/golden.py status   # counts + mismatch table, no gate

Privacy: entries hold only paths + counts (never text_blob/first_msg/
bash_commands) — and the file itself is gitignored; this repo is public.
Spec: docs/specs/2026-07-17-classification-golden-corpus-design.md
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "timecore"))

import yaml

from classify import ROOT_REDIRECT, classify_session, walk_registry


# --- corpus file ------------------------------------------------------------

def load_golden(path):
    p = Path(path)
    if not p.exists():
        return {"entries": []}
    with open(p) as f:
        return yaml.safe_load(f) or {"entries": []}


def save_golden(path, data):
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    tmp.replace(p)


# --- replay -----------------------------------------------------------------

def load_inputs(registry_path, rules_path):
    """Live classification inputs + the set of currently-valid bucket paths."""
    with open(registry_path) as f:
        registry = yaml.safe_load(f)
    rules = {}
    rp = Path(rules_path)
    if rp.exists():
        rules = yaml.safe_load(rp.read_text()) or {}
    flat = sorted(walk_registry(registry["buckets"]), key=lambda b: -b["depth"])
    excluded = registry.get("exclude_paths") or []
    lde = rules.get("session_launch_dir_exact") or {}
    valid = {tuple(b["path"]) for b in flat}
    valid |= {tuple(v) for v in ROOT_REDIRECT.values()}
    return flat, excluded, lde, valid


def replay_entry(entry, flat, excluded, lde):
    ev = entry.get("evidence") or {}
    sess = {"encoded": ev.get("encoded", ""),
            "edit_paths": ev.get("edit_paths") or {},
            "read_paths": ev.get("read_paths") or {}}
    return classify_session(sess, flat, excluded, lde)


def compute_mismatches(golden, flat, excluded, lde, valid_buckets):
    """One record per disagreeing entry. kind: 'stale' (expected bucket no
    longer in the registry — checked FIRST so a rename can't hide among
    movers), else the entry's status ('confirmed' or 'provisional').
    Only the bucket is compared; reason/scores ride along as diagnostics."""
    out = []
    for e in golden.get("entries", []):
        exp = e.get("expected_bucket")
        exp_t = tuple(exp) if exp else None
        if exp_t is not None and exp_t not in valid_buckets:
            out.append({"entry": e, "kind": "stale", "got": None,
                        "reason": None, "scores": {}})
            continue
        got, reason, scores = replay_entry(e, flat, excluded, lde)
        got_t = tuple(got) if got else None
        if got_t != exp_t:
            out.append({"entry": e, "kind": e.get("status", "provisional"),
                        "got": got, "reason": reason, "scores": scores})
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_golden_harness.py -q`
Expected: 6 passed.

- [ ] **Step 5: Wire `config.GOLDEN` + gitignore**

In `src/pulse/config.py`, directly under the `RULES = ...` line:

```python
GOLDEN = _resolve(_cfg["golden"]) if _cfg.get("golden") else DATA_DIR / "golden-classifications.yaml"
```

In `.gitignore`, directly under `disambiguation-rules.yaml`:

```
golden-classifications.yaml
```

- [ ] **Step 6: Full suite + commit**

Run: `python3 -m pytest -q` — all green.

```bash
git add src/pulse/golden.py src/pulse/config.py .gitignore tests/test_golden_harness.py
git commit -m "feat(golden): corpus schema, replay, mismatch computation + config.GOLDEN (#58)"
```

---

### Task 3: `seed` subcommand + CLI skeleton

**Files:**
- Modify: `src/pulse/golden.py` (append)
- Test: `tests/test_golden_harness.py` (append)

**Interfaces:**
- Consumes: `load_golden`/`save_golden` (Task 2), `.cache/prematch.json` shape (`confident.sessions[]` with `filepath`, `bucket_path`, `encoded`, `edit_paths`, `read_paths`).
- Produces: `seed(prematch_path, golden_path) -> int` (count added). CLI `main(argv)` with subcommands; flags `--golden`, `--registry`, `--rules`, `--prematch` default to `config.*` / `config.DATA_DIR/".cache"/"prematch.json"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_golden_harness.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_golden_harness.py -q`
Expected: AttributeError — `golden` has no attribute `seed`.

- [ ] **Step 3: Implement `seed` + CLI skeleton**

Append to `src/pulse/golden.py`:

```python
# --- seed -------------------------------------------------------------------

def seed(prematch_path, golden_path):
    """Import current confident sessions as provisional entries. Append-only,
    idempotent by id; existing entries (confirmed OR provisional) are never
    modified. Returns the number of entries added."""
    with open(prematch_path) as f:
        pm = json.load(f)
    golden = load_golden(golden_path)
    have = {e["id"] for e in golden["entries"]}
    added = 0
    for s in pm.get("confident", {}).get("sessions", []):
        sid = Path(s["filepath"]).name
        if sid in have:
            continue
        golden["entries"].append({
            "id": sid,
            "status": "provisional",
            "expected_bucket": list(s["bucket_path"]) if s.get("bucket_path") else None,
            "evidence": {
                "encoded": s.get("encoded", ""),
                "edit_paths": s.get("edit_paths") or {},
                "read_paths": s.get("read_paths") or {},
            },
        })
        have.add(sid)
        added += 1
    save_golden(golden_path, golden)
    return added


# --- CLI --------------------------------------------------------------------

def main(argv=None):
    import config

    ap = argparse.ArgumentParser(description="Classification golden corpus (#58)")
    ap.add_argument("--golden", default=str(config.GOLDEN))
    ap.add_argument("--registry", default=str(config.REGISTRY))
    ap.add_argument("--rules", default=str(config.RULES))
    ap.add_argument("--prematch", default=str(config.DATA_DIR / ".cache" / "prematch.json"))
    ap.add_argument("cmd", choices=["seed", "review", "status"])
    args = ap.parse_args(argv)

    if args.cmd == "seed":
        n = seed(args.prematch, args.golden)
        total = len(load_golden(args.golden)["entries"])
        print(f"seeded {n} new provisional entries ({total} total) -> {args.golden}")
        return 0
    flat, excluded, lde, valid = load_inputs(args.registry, args.rules)
    golden = load_golden(args.golden)
    mm = compute_mismatches(golden, flat, excluded, lde, valid)
    if args.cmd == "status":
        return status(golden, mm)
    return review(golden, mm, args.golden)


if __name__ == "__main__":
    sys.exit(main())
```

(`review` and `status` don't exist yet — Task 5 adds them; that's fine, the CLI only dereferences them for those subcommands. If a reviewer objects, stub them raising `SystemExit("not implemented; Task 5")`.)

- [ ] **Step 4: Run tests + commit**

Run: `python3 -m pytest -q` — all green.

```bash
git add src/pulse/golden.py tests/test_golden_harness.py
git commit -m "feat(golden): seed subcommand + CLI skeleton (#58)"
```

---

### Task 4: The pytest gate

**Files:**
- Modify: `src/pulse/golden.py` (append `format_failures`)
- Create: `tests/test_golden_classifications.py`
- Test: `tests/test_golden_harness.py` (append format tests)

**Interfaces:**
- Consumes: `compute_mismatches` (Task 2), `config.GOLDEN/REGISTRY/RULES`.
- Produces: `format_failures(mismatches) -> str` (grouped: stale, confirmed, provisional; provisional block ends with the review-CLI pointer).

- [ ] **Step 1: Write the failing format tests**

Append to `tests/test_golden_harness.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_golden_harness.py -q`
Expected: AttributeError — no attribute `format_failures`.

- [ ] **Step 3: Implement `format_failures` + the gate test**

Append to `src/pulse/golden.py` (before `main`):

```python
def format_failures(mismatches):
    """Human-readable verdict table for the pytest gate."""
    stale = [m for m in mismatches if m["kind"] == "stale"]
    conf = [m for m in mismatches if m["kind"] == "confirmed"]
    prov = [m for m in mismatches if m["kind"] == "provisional"]
    lines = []
    if stale:
        lines.append(f"{len(stale)} stale label(s) — expected bucket no longer in registry:")
        lines += [f"  {m['entry']['id']}: {m['entry']['expected_bucket']}" for m in stale]
    if conf:
        lines.append(f"{len(conf)} REGRESSION against hand-validated truth:")
        lines += [f"  {m['entry']['id']}: {m['entry']['expected_bucket']} -> {m['got']} ({m['reason']})"
                  for m in conf]
    if prov:
        lines.append(f"{len(prov)} unreviewed mover(s) — run `python3 src/pulse/golden.py review`:")
        lines += [f"  {m['entry']['id']}: {m['entry']['expected_bucket']} -> {m['got']} ({m['reason']})"
                  for m in prov]
    return "\n".join(lines)
```

Create `tests/test_golden_classifications.py`:

```python
"""The golden-corpus gate (#58): replay every hand-/machine-labeled entry
through the shipping cascade against the LIVE registry + rules; fail on any
bucket change. SKIPS (visibly) on machines without a corpus (external users,
CI) — the corpus is private user data and never ships in this public repo.
Spec: docs/specs/2026-07-17-classification-golden-corpus-design.md
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src' / 'pulse'))
import pytest

import config
import golden as G


def test_golden_corpus_replay():
    if not config.GOLDEN.exists():
        pytest.skip(f"no golden corpus at {config.GOLDEN} (external user / CI)")
    if not config.REGISTRY.exists():
        pytest.skip(f"no registry at {config.REGISTRY}")
    data = G.load_golden(config.GOLDEN)
    flat, excluded, lde, valid = G.load_inputs(config.REGISTRY, config.RULES)
    mm = G.compute_mismatches(data, flat, excluded, lde, valid)
    if mm:
        pytest.fail(G.format_failures(mm), pytrace=False)
```

- [ ] **Step 4: Run + commit**

Run: `python3 -m pytest tests/test_golden_harness.py tests/test_golden_classifications.py -q`
Expected: harness tests pass; gate test SKIPS in the worktree (no `golden-classifications.yaml` at the worktree root — expected; real-data run happens in Task 7).

```bash
git add src/pulse/golden.py tests/test_golden_classifications.py tests/test_golden_harness.py
git commit -m "feat(golden): pytest gate + failure formatting (#58)"
```

---

### Task 5: `review` + `status` subcommands

**Files:**
- Modify: `src/pulse/golden.py` (append)
- Test: `tests/test_golden_harness.py` (append `apply_verdict` tests)

**Interfaces:**
- Consumes: mismatch records (Task 2), `save_golden`.
- Produces: `apply_verdict(entry, got_bucket, verdict, today=None) -> bool` (True if entry changed). `review(golden, mismatches, golden_path) -> int`, `status(golden, mismatches) -> int` (exit codes).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_golden_harness.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_golden_harness.py -q`
Expected: AttributeError — no attribute `apply_verdict`.

- [ ] **Step 3: Implement**

Append to `src/pulse/golden.py` (before `main`):

```python
# --- review / status --------------------------------------------------------

def apply_verdict(entry, got_bucket, verdict, today=None):
    """'new' = the change is right: re-baseline expected to got_bucket and
    confirm. 'old' = the change is a regression: pin current expected and
    confirm (the gate stays red until the heuristic is fixed). 'skip' = leave
    untouched. Returns True if the entry changed."""
    if verdict == "skip":
        return False
    if verdict == "new":
        entry["expected_bucket"] = list(got_bucket) if got_bucket else None
    entry["status"] = "confirmed"
    entry["labeled_at"] = today or date.today().isoformat()
    return True


def _show(m):
    e = m["entry"]
    ev = e.get("evidence") or {}
    print(f"\n--- {e['id']} [{m['kind']}]")
    print(f"  launch dir : {ev.get('encoded', '')}")
    print(f"  expected   : {e.get('expected_bucket')}")
    print(f"  replayed   : {m['got']} ({m['reason']})")
    if m["scores"]:
        top = sorted(m["scores"].items(), key=lambda kv: -kv[1])[:5]
        print(f"  scores     : {top}")
    paths = list((ev.get("edit_paths") or {}).items()) + \
            list((ev.get("read_paths") or {}).items())
    for p, c in sorted(paths, key=lambda kv: -kv[1])[:8]:
        print(f"    {c:>3}x {p}")


def review(golden, mismatches, golden_path):
    if not mismatches:
        pending = [e for e in golden["entries"] if e.get("status") != "confirmed"]
        print(f"no mismatches. {len(pending)} provisional entries — "
              f"confirm anchors proactively? Walking them (Ctrl-C to stop; [c]onfirm / [s]kip)")
        changed = 0
        try:
            for e in pending:
                print(f"\n--- {e['id']}  expected={e.get('expected_bucket')}  "
                      f"launch={((e.get('evidence') or {}).get('encoded', ''))}")
                v = input("[c]onfirm / [s]kip > ").strip().lower()
                if v == "c" and apply_verdict(e, e.get("expected_bucket"), "old"):
                    changed += 1
        except (KeyboardInterrupt, EOFError):
            print()
        if changed:
            save_golden(golden_path, golden)
        print(f"confirmed {changed}")
        return 0
    changed = 0
    try:
        for m in mismatches:
            _show(m)
            if m["kind"] == "stale":
                v = input("[n]ew: re-baseline to replayed / [s]kip (or fix the label by hand) > ")
                v = {"n": "new", "s": "skip"}.get(v.strip().lower(), "skip")
            else:
                v = input("[n]ew-right / [o]ld-right / [s]kip > ")
                v = {"n": "new", "o": "old", "s": "skip"}.get(v.strip().lower(), "skip")
            if apply_verdict(m["entry"], m["got"], v):
                changed += 1
    except (KeyboardInterrupt, EOFError):
        print("\n(stopped; verdicts so far are saved)")
    if changed:
        save_golden(golden_path, golden)
    print(f"\nrecorded {changed} verdict(s); re-run pytest to see the gate.")
    return 0


def status(golden, mismatches):
    entries = golden.get("entries", [])
    conf = sum(1 for e in entries if e.get("status") == "confirmed")
    print(f"{len(entries)} entries: {conf} confirmed, {len(entries) - conf} provisional")
    if mismatches:
        print(format_failures(mismatches))
    else:
        print("0 mismatches — gate is green.")
    return 0
```

- [ ] **Step 4: Run + commit**

Run: `python3 -m pytest -q` — all green.

```bash
git add src/pulse/golden.py tests/test_golden_harness.py
git commit -m "feat(golden): review + status subcommands (#58)"
```

---

### Task 6: Vendored/canonical sync — mirror + guard test

**Files:**
- Create: `tests/test_timecore_sync.py`
- Modify (OUTSIDE this repo, separate monorepo commit): `<monorepo>/.claude/skills/code-blocks/blocks/timecore/classify.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure file comparison).
- Produces: the two `classify.py` copies byte-identical; a committed test enforcing it on machines that have both.

Background: the canonical copy currently lags the vendored one by `classify_session_by_launch_dir_exact` (#40) and, after Task 1, `classify_session`. Both are pure additions — mirroring is safe for the deploy-week consumer.

- [ ] **Step 1: Write the failing test**

Create `tests/test_timecore_sync.py`:

```python
"""Guard: the vendored timecore/classify.py must stay byte-identical to the
canonical copy in the monorepo (deploy-week consumer) — the #55 spike's sync
rule. Skips on machines without the monorepo layout (external users, CI):
there the vendored copy is simply the only copy.
"""
import pathlib
import pytest

VENDORED = pathlib.Path(__file__).resolve().parents[1] / "src" / "pulse" / "timecore" / "classify.py"
# pulse repo root sits at <monorepo>/projects/personal/pulse in David's layout
CANONICAL = (pathlib.Path(__file__).resolve().parents[1].parents[2]
             / ".claude" / "skills" / "code-blocks" / "blocks" / "timecore" / "classify.py")


def test_vendored_matches_canonical():
    if not CANONICAL.exists():
        pytest.skip(f"no canonical copy at {CANONICAL} (standalone clone)")
    assert VENDORED.read_bytes() == CANONICAL.read_bytes(), (
        "timecore/classify.py has diverged from the canonical copy — apply the "
        "change to BOTH (spike rule, docs/specs/2026-07-08-evidence-policy-spike.md)")
```

- [ ] **Step 2: Run to verify it fails (or skips)**

Run: `python3 -m pytest tests/test_timecore_sync.py -q`
- In the worktree (`.worktrees/issue-58`): SKIPS — `parents` resolves inside the pulse checkout, no canonical there. That's the known limitation; the test enforces on the MAIN checkout.
- To see the real failure, run from the main checkout after Task 7's merge-back — or verify now by hand: `diff src/pulse/timecore/classify.py <monorepo>/.claude/skills/code-blocks/blocks/timecore/classify.py` → shows the divergence.

- [ ] **Step 3: Mirror the vendored copy to canonical**

```bash
cp src/pulse/timecore/classify.py \
   <monorepo>/.claude/skills/code-blocks/blocks/timecore/classify.py
cd <monorepo> && \
  git add .claude/skills/code-blocks/blocks/timecore/classify.py && \
  git commit -m "sync(timecore): mirror classify.py from pulse — launch_dir_exact (#40) + classify_session (pulse#58)" && \
  cd - >/dev/null
```

(Monorepo commit — NOT pushed as part of this task; David's normal monorepo flow handles it.)

- [ ] **Step 4: Verify identity + commit the test**

Run: `diff src/pulse/timecore/classify.py <monorepo>/.claude/skills/code-blocks/blocks/timecore/classify.py && echo IDENTICAL`
Expected: `IDENTICAL`.

```bash
git add tests/test_timecore_sync.py
git commit -m "test: guard vendored/canonical timecore classify.py byte-identity (#58)"
```

---

### Task 7: Real-data E2E, spec touch-up, CHANGELOG

**Files:**
- Modify: `docs/specs/2026-07-17-classification-golden-corpus-design.md` (CLI invocation wording)
- Modify: `CHANGELOG.md` (`## [Unreleased]`)

- [ ] **Step 1: Seed the real corpus (explicit paths — user data lives in the MAIN checkout)**

```bash
MAIN=<main-pulse-checkout>
python3 src/pulse/golden.py \
  --golden   $MAIN/golden-classifications.yaml \
  --registry $MAIN/bucket-registry.yaml \
  --rules    $MAIN/disambiguation-rules.yaml \
  --prematch $MAIN/.cache/prematch.json \
  seed
```

Expected: `seeded ~296 new provisional entries` (count = `sessions_confident` in the cache).

- [ ] **Step 2: Status — the baseline must be green**

Same flags, `status`. Expected: `0 mismatches — gate is green.` (seed derives expected buckets from the same cascade the replay runs; any mismatch here means Task 1's extraction is NOT behavior-preserving — STOP and fix.)

Also verify privacy: `grep -c 'text_blob\|first_msg\|bash_commands' $MAIN/golden-classifications.yaml` → `0`, and `cd $MAIN && git status --short` → golden file NOT listed (gitignored).

- [ ] **Step 3: Spec wording fix**

In `docs/specs/2026-07-17-classification-golden-corpus-design.md`, replace every `python3 -m pulse.golden` with `python3 src/pulse/golden.py` (3 occurrences: §3, §4 heading, §3 failure text) — the repo has no package install; CLIs run by path.

- [ ] **Step 4: CHANGELOG entry**

Under `## [Unreleased]` in `CHANGELOG.md`:

```markdown
- Classification golden corpus: hand-validated regression gate for classifier
  heuristic changes — `golden-classifications.yaml` (gitignored) + pytest gate +
  `python3 src/pulse/golden.py seed|review|status` (#58)
```

- [ ] **Step 5: Full suite + commit**

Run: `python3 -m pytest -q` — all green (gate + sync tests SKIP in the worktree; they arm on the main checkout after merge).

```bash
git add docs/specs/2026-07-17-classification-golden-corpus-design.md CHANGELOG.md
git commit -m "docs(golden): CLI invocation wording + CHANGELOG (#58)"
```

---

## Post-merge (work-mode QA, not a plan task)

From the MAIN checkout after merge: `git pull`, `python3 -m pytest -q` — the gate must now RUN (not skip) and pass green; the sync test must RUN and pass. Then `python3 src/pulse/golden.py status`. App QA (`--qa`): relaunch Pulse and confirm the menu-bar card still renders — this change touches the shared classify path, so the far-QA run is required even though no UI changed. Next issue (#55) then starts by confirming the spike's 10 movers via `review`.
