#!/usr/bin/env python3
"""Render the latest releases from CHANGELOG into a marker-bounded README region.

Single source of truth is CHANGELOG.md (Keep a Changelog). The README "What's New"
block shows the latest N *released* versions — it is a function of the CHANGELOG
alone, NOT of the wall clock, so the committed README is stable until a release is
cut and the `--check` gate only fires on real CHANGELOG changes. Pure
parse/render/splice functions are unit-tested; the CLI wires them to the real files.
This is a dev/CI tool — never imported by the running app, stdlib only.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

START = "<!-- RECENT:START -->"
END = "<!-- RECENT:END -->"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAX_RELEASES = 3


@dataclass
class Release:
    version: str
    day: date
    # ordered (category, [entries]); category "" holds bullets with no `### Heading`.
    sections: list[tuple[str, list[str]]] = field(default_factory=list)


_REL_RE = re.compile(r"^##\s*\[(?P<ver>[^\]]+)\]\s*-\s*(?P<date>\d{4}-\d{2}-\d{2})\s*$")
_LOOSE_REL_RE = re.compile(r"^##\s*\[?[^\]]*\d+\.\d+")   # "looks like a release heading"
_UNRELEASED_RE = re.compile(r"^##\s*\[?unreleased", re.IGNORECASE)
_CAT_RE = re.compile(r"^###\s+(?P<cat>.+?)\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(?P<text>.+?)\s*$")


def _warn(msg: str) -> None:
    print(f"render_recent_changes: {msg}", file=sys.stderr)


def parse_changelog(text: str) -> list[Release]:
    """Parse Keep a Changelog text into dated releases (as-written order).

    ``## [Unreleased]`` (and any undated ``## `` heading) is skipped. A heading that
    *looks* like a release but fails to parse — bad bracket form, single-digit or
    calendar-invalid date — is skipped with a stderr warning rather than silently
    dropped or crashing the run.
    """
    releases: list[Release] = []
    cur: Release | None = None
    for line in text.splitlines():
        m = _REL_RE.match(line)
        if m:
            try:
                day = datetime.strptime(m.group("date"), "%Y-%m-%d").date()
            except ValueError:
                _warn(f"invalid date in heading, skipping: {line.strip()!r}")
                cur = None
                continue
            cur = Release(version=m.group("ver").strip(), day=day)
            releases.append(cur)
            continue
        if line.startswith("## "):                      # undated H2 ends release context
            if not _UNRELEASED_RE.match(line) and _LOOSE_REL_RE.match(line):
                _warn(f"heading looks like a release but did not parse, skipping: {line.strip()!r}")
            cur = None
            continue
        if cur is None:
            continue
        cm = _CAT_RE.match(line)
        if cm:
            cur.sections.append((cm.group("cat"), []))
            continue
        bm = _BULLET_RE.match(line)
        if bm:
            if not cur.sections:                        # bullet before any `### Category`
                cur.sections.append(("", []))           # keep it under an unlabeled section
            cur.sections[-1][1].append(bm.group("text"))
    return releases


def render_recent(releases: list[Release], max_releases: int = DEFAULT_MAX_RELEASES) -> str:
    """Markdown block (without markers) for the latest ``max_releases`` releases.

    Newest first. Independent of the current date — only the CHANGELOG content.
    """
    latest = sorted(releases, key=lambda r: r.day, reverse=True)[:max_releases]
    lines = ["## What's New", ""]
    if not latest:
        lines.append("_No releases yet — see [CHANGELOG.md](CHANGELOG.md)._")
        return "\n".join(lines)
    for r in latest:
        lines.append(f"**{r.version}** — {r.day.isoformat()}")
        for cat, entries in r.sections:
            for e in entries:
                lines.append(f"- _{cat}:_ {e}" if cat else f"- {e}")
        lines.append("")
    lines.append("_Full history in [CHANGELOG.md](CHANGELOG.md)._")
    return "\n".join(lines)


def splice(readme_text: str, block: str) -> str:
    """Replace text strictly between START and END markers with ``block``.

    Markers are preserved; idempotent. Raises ValueError if markers are absent or
    out of order (END before START).
    """
    if START not in readme_text or END not in readme_text:
        raise ValueError(f"README missing markers {START!r}/{END!r}")
    if readme_text.index(START) > readme_text.index(END):
        raise ValueError(f"README markers out of order: {END!r} appears before {START!r}")
    pre, rest = readme_text.split(START, 1)
    _mid, post = rest.split(END, 1)
    return f"{pre}{START}\n{block}\n{END}{post}"


def render_readme(changelog_text: str, readme_text: str,
                  max_releases: int = DEFAULT_MAX_RELEASES) -> str:
    block = render_recent(parse_changelog(changelog_text), max_releases)
    return splice(readme_text, block)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--changelog", type=Path, default=REPO_ROOT / "CHANGELOG.md")
    ap.add_argument("--readme", type=Path, default=REPO_ROOT / "README.md")
    ap.add_argument("--max-releases", type=int, default=DEFAULT_MAX_RELEASES,
                    help="How many of the latest releases to show (default %(default)s).")
    ap.add_argument("--check", action="store_true",
                    help="Exit 1 if README is stale instead of writing it.")
    args = ap.parse_args(argv)

    try:
        readme_text = args.readme.read_text()
        updated = render_readme(args.changelog.read_text(), readme_text, args.max_releases)
    except FileNotFoundError as e:
        _warn(f"file not found: {e.filename}")
        return 2
    except ValueError as e:
        _warn(str(e))
        return 2

    if updated == readme_text:
        print("README recent-changes block already up to date.")
        return 0
    if args.check:
        print("README recent-changes block is STALE — run scripts/render_recent_changes.py",
              file=sys.stderr)
        return 1
    args.readme.write_text(updated)
    print("Updated README recent-changes block.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
