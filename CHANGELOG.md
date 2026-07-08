# Changelog

All notable changes to Pulse are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- Panel period toggle gains a third `day` segment (day · week · month) — clicking `day` switches every engagement/group row to today's hours. A day has no cap, so day rows render track-style (hours, no bar) and the choice persists across panel reopens like week/month (#39).
- Classifier: exact launch-dir → bucket fallback (`session_launch_dir_exact` in the rules file), so an umbrella root can be mapped to a bucket without its subdirectories inheriting the mapping (#40).
- "Update available" banner on the menu-bar card when the installed clone is behind `shanerconsulting/pulse` main — shows the exact one-line update command (`git pull && bash install-mac.sh`) with a copy button. Detection compares local HEAD to the remote main sha via the public GitHub API (stdlib urllib, no auth); it runs on the snapshot tick, is throttled (a real request at most every 6h, cached in `state.json`), and is fully fail-silent — offline or GitHub-unreachable shows nothing and never blocks the card. Only git shas cross the wire; when the clone is current the card stays silent (#25).

### Changed
- Session scan keeps an incremental parse cache so unchanged JSONL files (same path+mtime+size) skip re-reading every refresh cycle. The expensive per-file read is cached under the gitignored `.cache/`; the rolling 30d window is re-applied cheaply each run, so output is byte-identical to the uncached path. Measured ~2.9x faster on a warm cache (#30).

## [0.1.0] - 2026-06-29
### Added
- First public release of Pulse: a local macOS menu-bar app that measures billable time across projects from Claude Code session activity.
- Calendar meetings folded into the time totals — resolved meetings count toward the hour bars and appetite caps, attributed by attendee.
- User-defined roll-up groups with a week/month toggle on the menu-bar card.
- Standalone install: the pipeline runs from a fresh clone with no external checkout, building a repo-local `.venv` the LaunchAgent shares.

### Fixed
- Refresh pipeline no longer silently jams under load — snapshot timeouts kill the process group and surface staleness instead of freezing the card (#28).
- Calendar dependencies are pinned in `requirements.txt`, so meetings no longer silently fail to count after install (#26).
