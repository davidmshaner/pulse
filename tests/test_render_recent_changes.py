import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "render_recent_changes",
    Path(__file__).resolve().parent.parent / "scripts" / "render_recent_changes.py",
)
rrc = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = rrc          # dataclass needs the module registered
_SPEC.loader.exec_module(rrc)

SAMPLE = """\
# Changelog

## [Unreleased]
### Added
- something not yet released

## [0.2.0] - 2026-06-20
### Added
- roll-up groups
### Fixed
- snapshot timeout no longer freezes the card

## [0.1.0] - 2026-05-01
### Added
- first cut
"""


def test_parse_skips_unreleased_and_reads_dates():
    rels = rrc.parse_changelog(SAMPLE)
    assert [r.version for r in rels] == ["0.2.0", "0.1.0"]
    assert rels[0].day == date(2026, 6, 20)


def test_parse_groups_sections_and_entries():
    rels = rrc.parse_changelog(SAMPLE)
    secs = dict((c, e) for c, e in rels[0].sections)
    assert secs["Added"] == ["roll-up groups"]
    assert secs["Fixed"] == ["snapshot timeout no longer freezes the card"]


def test_render_recent_filters_by_window_newest_first():
    rels = rrc.parse_changelog(SAMPLE)
    out = rrc.render_recent(rels, today=date(2026, 6, 29), days=30)
    assert "**0.2.0** — 2026-06-20" in out
    assert "0.1.0" not in out                      # 2026-05-01 is outside 30 days
    assert "_Added:_ roll-up groups" in out


def test_render_recent_empty_window_has_fallback():
    rels = rrc.parse_changelog(SAMPLE)
    out = rrc.render_recent(rels, today=date(2027, 1, 1), days=30)
    assert "No releases in the last 30 days" in out


def test_splice_replaces_between_markers_only():
    readme = f"intro\n{rrc.START}\nOLD\n{rrc.END}\noutro\n"
    out = rrc.splice(readme, "NEW")
    assert out == f"intro\n{rrc.START}\nNEW\n{rrc.END}\noutro\n"


def test_splice_is_idempotent():
    readme = f"intro\n{rrc.START}\nOLD\n{rrc.END}\noutro\n"
    once = rrc.splice(readme, "NEW")
    twice = rrc.splice(once, "NEW")
    assert once == twice


def test_splice_requires_markers():
    with pytest.raises(ValueError):
        rrc.splice("no markers here", "NEW")


# --- Task 2: CLI behavior --------------------------------------------------

def _write(tmp_path):
    cl = tmp_path / "CHANGELOG.md"
    rd = tmp_path / "README.md"
    cl.write_text(SAMPLE)
    rd.write_text(f"intro\n{rrc.START}\nstale\n{rrc.END}\noutro\n")
    return cl, rd


def test_main_writes_block(tmp_path):
    cl, rd = _write(tmp_path)
    rc = rrc.main(["--changelog", str(cl), "--readme", str(rd), "--days", "100000"])
    assert rc == 0
    assert "## What's New" in rd.read_text()
    assert "stale" not in rd.read_text()


def test_main_check_returns_1_when_stale(tmp_path):
    cl, rd = _write(tmp_path)
    rc = rrc.main(["--changelog", str(cl), "--readme", str(rd), "--days", "100000", "--check"])
    assert rc == 1
    assert "stale" in rd.read_text()             # --check must NOT modify the file


def test_main_check_returns_0_when_current(tmp_path):
    cl, rd = _write(tmp_path)
    rrc.main(["--changelog", str(cl), "--readme", str(rd), "--days", "100000"])
    rc = rrc.main(["--changelog", str(cl), "--readme", str(rd), "--days", "100000", "--check"])
    assert rc == 0
