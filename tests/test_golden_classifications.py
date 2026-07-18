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
