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
        data = yaml.safe_load(f) or {"entries": []}
    if not data.get("entries"):
        data["entries"] = []
    return data


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
            got, reason, scores = replay_entry(e, flat, excluded, lde)
            out.append({"entry": e, "kind": "stale", "got": got,
                        "reason": reason, "scores": scores})
            continue
        got, reason, scores = replay_entry(e, flat, excluded, lde)
        got_t = tuple(got) if got else None
        if e.get("deterministic") is False:
            # Hand-ruled ambiguous shape (#57): the cascade must DECLINE
            # (needs_llm) — any confident assignment is the regression.
            # expected_bucket stays as the human-truth record (and still
            # gets the stale check above).
            if got_t is not None:
                out.append({"entry": e, "kind": e.get("status", "provisional"),
                            "got": got, "reason": reason, "scores": scores})
            continue
        if got_t != exp_t:
            out.append({"entry": e, "kind": e.get("status", "provisional"),
                        "got": got, "reason": reason, "scores": scores})
    return out


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


# --- format & gate ----------------------------------------------------------

def format_failures(mismatches):
    """Human-readable verdict table for the pytest gate."""
    stale = [m for m in mismatches if m["kind"] == "stale"]
    conf = [m for m in mismatches if m["kind"] == "confirmed"]
    prov = [m for m in mismatches if m["kind"] not in ("stale", "confirmed")]
    lines = []
    if stale:
        lines.append(f"{len(stale)} stale label(s) — expected bucket no longer in registry:")
        lines += [f"  {m['entry']['id']}: {m['entry']['expected_bucket']} -> {m['got']} ({m['reason']}) [stale label]"
                  for m in stale]
    if conf:
        lines.append(f"{len(conf)} REGRESSION against hand-validated truth:")
        lines += [f"  {m['entry']['id']}: {m['entry']['expected_bucket']} -> {m['got']} ({m['reason']})"
                  for m in conf]
    if prov:
        lines.append(f"{len(prov)} unreviewed mover(s) — run `python3 src/pulse/golden.py review`:")
        lines += [f"  {m['entry']['id']}: {m['entry']['expected_bucket']} -> {m['got']} ({m['reason']})"
                  for m in prov]
    return "\n".join(lines)


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
                if v == "c" and apply_verdict(e, None, "old"):
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
