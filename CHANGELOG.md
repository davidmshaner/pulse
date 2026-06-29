# Changelog

All notable changes to Pulse are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-29
### Added
- First public release of Pulse: a local macOS menu-bar app that measures billable time across projects from Claude Code session activity.
- Calendar meetings folded into the time totals — resolved meetings count toward the hour bars and appetite caps, attributed by attendee.
- User-defined roll-up groups with a week/month toggle on the menu-bar card.
- Standalone install: the pipeline runs from a fresh clone with no external checkout, building a repo-local `.venv` the LaunchAgent shares.

### Fixed
- Refresh pipeline no longer silently jams under load — snapshot timeouts kill the process group and surface staleness instead of freezing the card (#28).
- Calendar dependencies are pinned in `requirements.txt`, so meetings no longer silently fail to count after install (#26).
