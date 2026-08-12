# Changelog

All notable changes to Pulse are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Changed
- Worktree-path normalization in the classifier: file evidence gathered inside a
  repo's git worktrees (`<repo>/.claude/worktrees/<name>/<sub>` or
  `<repo>/.worktrees/<name>/<sub>`) now matches the claims of its canonical repo
  location, so agent/dev sessions running in worktrees inherit sub-bucket claims
  (and exclusions) instead of falling back to the parent bucket (#69)
- Engagement rows now nest inside their group's card section: each group's direct
  member engagements render indented one level deeper than the group (after its
  sub-group subtrees), in both the panel and the menu-bar text fallback, so the
  visual hierarchy matches the configured roll-up tree — previously every
  engagement rendered in one flat list below all groups. An engagement listed by
  both a parent and its sub-group nests under the sub-group (most-specific wins).
  Engagements in no group keep the flat tail; configs with no `groups:`, wildcard
  (`members: "*"`) groups, and legacy `total_budget:` configs render unchanged (#66)
- Minimum-confidence floor for file evidence: a single incidental read (weight 0.2)
  can no longer decide a session's bucket on its own. Sub-floor evidence is weighed
  against the launch-dir bucket instead: agreeing whispers defer to the launch dir,
  a whisper pointing inside a *child* of the launch bucket refines the session down
  to it (`file_evidence_refined`), and a whisper on a *different branch* routes the
  session to the LLM — hand-review of the golden corpus found confirmed sessions of
  that exact shape with opposite truths, so no deterministic answer is defensible.
  Any edit or two-plus reads decide as before. Corpus replay (289 sessions, 13
  hand-confirmed): 7 refined, 2 to the LLM, everything else unchanged (#57)

### Fixed
- File-evidence poisoning by catch-all global dirs: a registry claim that is exactly
  `~/.claude/skills` or `~/.claude/projects` no longer counts as file evidence
  (every session touches those dirs as a side effect, so such claims silently pulled
  other ventures' sessions into the claiming bucket). Deeper, specific claims still
  count; `prematch` warns when the registry carries a catch-all claim (#55)

### Added
- Per-session manual overrides: `session-overrides.yaml` (gitignored; path
  config-relocatable like the registry/rules) maps a session's JSONL basename to a
  bucket path, applied only where the cascade returns `needs_llm` — so a hand
  verdict on a whisper-ambiguous session sticks instead of recurring in
  `uncategorized.json` until it ages out. Real file evidence still wins over an
  override; `setup/RESOLVE.md` documents when to teach the registry vs write an
  override (#64)
- Classification golden corpus: hand-validated regression gate for classifier
  heuristic changes — `golden-classifications.yaml` (gitignored) + pytest gate +
  `python3 src/pulse/golden.py seed|review|status` (#58)

## [0.2.1] - 2026-07-08
### Fixed
- Nested group cards indent as a whole — border, title, bar, and sub-line shift together by depth — so hierarchy reads as containment instead of a floating title (#50).
- Update banner no longer shows a false "update available" on an up-to-date clone: if local HEAD changed since the last check and mismatches the 6h-cached remote sha (the user pulled past a stale cache), the check refreshes the remote before deciding instead of trusting the cache — a genuinely-behind clone still never refetches per-snapshot (#49).

## [0.2.0] - 2026-07-08
### Added
- Income-meter engagement flavor: `bill_rate: <$/hr>` in `appetite.yaml` meters cumulative dollars billed for the calendar month (`$ = month-to-date hours × rate`) instead of dividing a dollar value into an hour cap. `bill_rate` alone is a pure running meter (`$6,250 mo`, no bar); adding `monthly_cap_value: <$>` shows progress toward the ceiling with `$X left` / `OVER $X`, mirroring hour caps. The meter is monthly (resets on the 1st, matching invoicing); day/week rows keep hours. Mixing income-mode with the hour-cap vocabularies (`monthly_value`/`target_rate`/`weekly_hours`) — or a `monthly_cap_value` with no `bill_rate` — is a loud preflight error, never a silent miscount (#38).
- Panel period toggle gains a third `day` segment (day · week · month) — clicking `day` switches every engagement/group row to today's hours. A day has no cap, so day rows render track-style (hours, no bar) and the choice persists across panel reopens like week/month (#39).
- Classifier: exact launch-dir → bucket fallback (`session_launch_dir_exact` in the rules file), so an umbrella root can be mapped to a bucket without its subdirectories inheriting the mapping (#40).
- Nested groups: a group's `members` in `appetite.yaml` may now name other groups as well as engagements, so groups ladder up into a hierarchy (no new field — the tree reads top-down). The menu-bar card and panel render the nesting indented with correct rollup totals at each level; a group with no `weekly_hours`/`monthly_hours` is a capless roll-up (summed hours, no bar). Bucket splits are documented as a registry `children:` convention (each child's `source_path` a subpath of its parent). Config validation fails loudly — unknown group member, membership cycle, a nesting that double-counts an engagement (reachable via a group and its ancestor), or a registry child path outside its parent — instead of silently miscounting. An engagement reachable via multiple paths is counted once (#31).
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
