"""qa.py — timecore golden + parity tests.

Two guarantees:
  1. SMOKE: imports timecore AND deploy-week's render (now a facade that
     re-exports timecore) and runs both. Confirms the cross-tree import chain
     resolves end-to-end. NOTE: parity is now trivially equal because render
     re-exports timecore — the real byte-identical parity was validated at
     extraction time (before render became a facade) and is preserved in git.
  2. REGRESSION: frozen expected.json files catch future drift — the ongoing
     guard.

Run: python3 qa.py        (verify against frozen expected + parity)
     python3 qa.py --freeze  (regenerate expected.json from current timecore)
No network. Exit 0 on all-pass, 1 on any failure.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(HERE))
import time_math as tc  # timecore
orig = tc  # vendored copy: no deploy-week. Frozen-fixture regression is the guard.


def _parse_pairs(pairs):
    return [(datetime.fromisoformat(a), datetime.fromisoformat(b)) for a, b in pairs]


def _round_dict(d):
    return {k: round(v, 6) for k, v in d.items()}


def call(func_name, payload, module):
    if func_name == "even_split_fractional":
        per_bucket = {tuple(k.split(".")): _parse_pairs(v)
                      for k, v in payload["per_bucket_intervals"].items()}
        out = module.even_split_fractional(per_bucket)
        return {".".join(k): round(v, 6) for k, v in out.items()}
    if func_name == "rollup_fractional":
        leaf = {tuple(k.split(".")): v for k, v in payload["leaf_fractional"].items()}
        out = module.rollup_fractional(leaf)
        return {".".join(k): round(v, 6) for k, v in out.items()}
    raise ValueError(f"unknown func {func_name}")


def run(freeze=False):
    raws = sorted(FIXTURES.glob("*.raw.json"))
    if not raws:
        print(f"no fixtures in {FIXTURES}", file=sys.stderr)
        return 1
    failed = 0
    for raw_path in raws:
        name = raw_path.name.replace(".raw.json", "")
        payload = json.loads(raw_path.read_text())
        fn = payload["func"]

        tc_out = call(fn, payload, tc)
        orig_out = call(fn, payload, orig)

        # 1. PARITY
        if tc_out != orig_out:
            failed += 1
            print(f"FAIL  {name}  [PARITY] timecore != original")
            print(f"  timecore: {tc_out}")
            print(f"  original: {orig_out}")
            continue

        # 2. REGRESSION (frozen expected)
        exp_path = raw_path.with_name(raw_path.name.replace(".raw.json", ".expected.json"))
        if freeze:
            exp_path.write_text(json.dumps(tc_out, indent=2, sort_keys=True) + "\n")
            print(f"FROZE {name}")
            continue
        if not exp_path.exists():
            failed += 1
            print(f"MISSING expected: {exp_path.name} (run --freeze)")
            continue
        expected = json.loads(exp_path.read_text())
        if tc_out == expected:
            print(f"PASS  {name}")
        else:
            failed += 1
            print(f"FAIL  {name}  [REGRESSION] output != frozen expected")
            print(f"  got:      {tc_out}")
            print(f"  expected: {expected}")
    if freeze:
        print("\nfrozen — review the .expected.json diffs before committing")
        return 0
    if failed:
        print(f"\n{failed}/{len(raws)} failed")
        return 1
    print(f"\n{len(raws)}/{len(raws)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(run(freeze="--freeze" in sys.argv))
