#!/usr/bin/env python3
"""Render the last-N-days CHANGELOG entries into a marker-bounded README region.

Single source of truth is CHANGELOG.md (Keep a Changelog). Pure parse/render/splice
functions are unit-tested; the CLI wires them to the real files. This is a dev/CI
tool — never imported by the running app, stdlib only.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

START = "<!-- RECENT:START -->"
END = "<!-- RECENT:END -->"
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Release:
    version: str
    day: date
    sections: list[tuple[str, list[str]]] = field(default_factory=list)


_REL_RE = re.compile(r"^##\s*\[(?P<ver>[^\]]+)\]\s*-\s*(?P<date>\d{4}-\d{2}-\d{2})\s*$")
_CAT_RE = re.compile(r"^###\s+(?P<cat>.+?)\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(?P<text>.+?)\s*$")


def parse_changelog(text: str) -> list[Release]:
    """Parse Keep a Changelog text into dated releases (as-written order).

    ``## [Unreleased]`` (and any undated ``## `` heading) is skipped; only
    versioned, dated releases are returned.
    """
    releases: list[Release] = []
    cur: Release | None = None
    for line in text.splitlines():
        m = _REL_RE.match(line)
        if m:
            cur = Release(
                version=m.group("ver"),
                day=datetime.strptime(m.group("date"), "%Y-%m-%d").date(),
            )
            releases.append(cur)
            continue
        if line.startswith("## "):          # undated H2 (e.g. [Unreleased]) ends release context
            cur = None
            continue
        if cur is None:
            continue
        cm = _CAT_RE.match(line)
        if cm:
            cur.sections.append((cm.group("cat"), []))
            continue
        bm = _BULLET_RE.match(line)
        if bm and cur.sections:
            cur.sections[-1][1].append(bm.group("text"))
    return releases


def render_recent(releases: list[Release], today: date, days: int = 30) -> str:
    """Markdown block (without markers) for releases dated within the last ``days``."""
    cutoff = today - timedelta(days=days)
    recent = sorted(
        (r for r in releases if r.day >= cutoff),
        key=lambda r: r.day,
        reverse=True,
    )
    lines = ["## What's New", ""]
    if not recent:
        lines.append(f"_No releases in the last {days} days — see [CHANGELOG.md](CHANGELOG.md)._")
        return "\n".join(lines)
    for r in recent:
        lines.append(f"**{r.version}** — {r.day.isoformat()}")
        for cat, entries in r.sections:
            for e in entries:
                lines.append(f"- _{cat}:_ {e}")
        lines.append("")
    lines.append("_Full history in [CHANGELOG.md](CHANGELOG.md)._")
    return "\n".join(lines)


def splice(readme_text: str, block: str) -> str:
    """Replace text strictly between START and END markers with ``block``.

    Markers are preserved; idempotent. Raises ValueError if markers are absent.
    """
    if START not in readme_text or END not in readme_text:
        raise ValueError(f"README missing markers {START!r}/{END!r}")
    pre, rest = readme_text.split(START, 1)
    _mid, post = rest.split(END, 1)
    return f"{pre}{START}\n{block}\n{END}{post}"


def render_readme(changelog_text: str, readme_text: str, today: date, days: int = 30) -> str:
    block = render_recent(parse_changelog(changelog_text), today, days)
    return splice(readme_text, block)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--changelog", type=Path, default=REPO_ROOT / "CHANGELOG.md")
    ap.add_argument("--readme", type=Path, default=REPO_ROOT / "README.md")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--check", action="store_true",
                    help="Exit 1 if README is stale instead of writing it.")
    args = ap.parse_args(argv)

    readme_text = args.readme.read_text()
    updated = render_readme(args.changelog.read_text(), readme_text, date.today(), args.days)
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
