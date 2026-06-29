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


def test_render_recent_shows_latest_n_newest_first():
    rels = rrc.parse_changelog(SAMPLE)
    out = rrc.render_recent(rels, max_releases=1)
    assert "**0.2.0** — 2026-06-20" in out
    assert "0.1.0" not in out                       # only the single latest release
    assert "_Added:_ roll-up groups" in out


def test_render_recent_is_date_independent():
    # Same CHANGELOG -> same block regardless of when it is rendered.
    rels = rrc.parse_changelog(SAMPLE)
    assert rrc.render_recent(rels) == rrc.render_recent(rels)
    out = rrc.render_recent(rels)
    assert "**0.2.0**" in out and "**0.1.0**" in out  # both shown (default max 3)


def test_render_recent_empty_has_fallback():
    out = rrc.render_recent([])
    assert "No releases yet" in out


def test_parse_orphan_bullet_not_dropped():
    text = "## [0.3.0] - 2026-06-25\n- bullet with no category\n"
    rels = rrc.parse_changelog(text)
    assert rels[0].sections == [("", ["bullet with no category"])]
    out = rrc.render_recent(rels)
    assert "- bullet with no category" in out        # rendered without an italic prefix


def test_parse_bad_date_warns_and_skips_without_crashing(capsys):
    text = "## [0.3.0] - 2026-13-05\n### Added\n- nope\n\n## [0.2.0] - 2026-06-20\n### Added\n- ok\n"
    rels = rrc.parse_changelog(text)               # must not raise
    assert [r.version for r in rels] == ["0.2.0"]
    assert "invalid date" in capsys.readouterr().err


def test_parse_malformed_release_heading_warns(capsys):
    text = "## 0.3.0 - 2026-06-25\n### Added\n- missing brackets\n"
    rrc.parse_changelog(text)
    assert "did not parse" in capsys.readouterr().err


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


def test_splice_rejects_out_of_order_markers():
    with pytest.raises(ValueError):
        rrc.splice(f"x\n{rrc.END}\ny\n{rrc.START}\nz\n", "NEW")


# --- CLI behavior ----------------------------------------------------------

def _write(tmp_path):
    cl = tmp_path / "CHANGELOG.md"
    rd = tmp_path / "README.md"
    cl.write_text(SAMPLE)
    rd.write_text(f"intro\n{rrc.START}\nstale\n{rrc.END}\noutro\n")
    return cl, rd


def test_main_writes_block(tmp_path):
    cl, rd = _write(tmp_path)
    rc = rrc.main(["--changelog", str(cl), "--readme", str(rd)])
    assert rc == 0
    assert "## What's New" in rd.read_text()
    assert "stale" not in rd.read_text()


def test_main_check_returns_1_when_stale(tmp_path):
    cl, rd = _write(tmp_path)
    rc = rrc.main(["--changelog", str(cl), "--readme", str(rd), "--check"])
    assert rc == 1
    assert "stale" in rd.read_text()             # --check must NOT modify the file


def test_main_check_returns_0_when_current(tmp_path):
    cl, rd = _write(tmp_path)
    rrc.main(["--changelog", str(cl), "--readme", str(rd)])
    rc = rrc.main(["--changelog", str(cl), "--readme", str(rd), "--check"])
    assert rc == 0


def test_main_missing_file_is_clean_error(tmp_path, capsys):
    rc = rrc.main(["--changelog", str(tmp_path / "nope.md"), "--readme", str(tmp_path / "x.md")])
    assert rc == 2
    assert "file not found" in capsys.readouterr().err


def test_main_missing_markers_is_clean_error(tmp_path, capsys):
    cl = tmp_path / "CHANGELOG.md"
    rd = tmp_path / "README.md"
    cl.write_text(SAMPLE)
    rd.write_text("no markers here\n")
    rc = rrc.main(["--changelog", str(cl), "--readme", str(rd)])
    assert rc == 2
    assert "missing markers" in capsys.readouterr().err
