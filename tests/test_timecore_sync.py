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
