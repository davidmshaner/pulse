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
