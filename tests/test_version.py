"""test_version.py — VERSION file is the single source of truth and pulse exposes it."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import pulse  # noqa: E402


def test_version_matches_file():
    assert pulse.__version__ == (REPO_ROOT / "VERSION").read_text().strip()


def test_version_is_semver():
    parts = pulse.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)
