# Pulse

<p align="center">
  <img src="assets/hero.png" alt="Pulse menu-bar card: time split across projects, over-budget in red" width="380">
</p>

<h2 align="center">Know where your time actually went.</h2>

If you work through Claude Code all day across more than one project, you have no
honest idea how much time each one got. Session length lies. Your starting folder
lies. Running three sessions at once lies. And the hour you spent in a meeting never
shows up at all. Pulse counts it right and puts it in your menu bar.

## Why this is hard

Measuring how your time splits across projects inside Claude Code looks trivial and
isn't. Every easy way to count it is wrong in a specific way:

- **Session length isn't work time.** You opened a tab at 9:00 and came back at 9:25.
  That's not 25 minutes of work. Pulse counts only the time your fingers were actually
  moving.
- **Turn count isn't signal.** Raw turns include noise, retries, and thinking out loud.
  Pulse measures real activity, not a turn tally.
- **Where you started isn't where the work went.** Start a session in one project's
  folder but do the work for another, and naive tracking counts it to the wrong one.
  Pulse attributes time by where the files actually landed.
- **Concurrency double-counts.** Three sessions at once isn't three times the hours.
  Pulse splits overlapping time so a minute is only ever counted once.
- **Meetings are invisible.** The hour on a call never lands in any log. Pulse folds in
  your calendar, and learns which people belong to which project so it attributes them
  automatically.

So the split is honest, whether you're billing clients, dividing time across your own
products, or just want to know where the day went.

<!-- RECENT:START -->
## What's New

**0.1.0** — 2026-06-29
- _Added:_ First public release of Pulse: a local macOS menu-bar app that measures billable time across projects from Claude Code session activity.
- _Added:_ Calendar meetings folded into the time totals — resolved meetings count toward the hour bars and appetite caps, attributed by attendee.
- _Added:_ User-defined roll-up groups with a week/month toggle on the menu-bar card.
- _Added:_ Standalone install: the pipeline runs from a fresh clone with no external checkout, building a repo-local `.venv` the LaunchAgent shares.
- _Fixed:_ Refresh pipeline no longer silently jams under load — snapshot timeouts kill the process group and surface staleness instead of freezing the card (#28).
- _Fixed:_ Calendar dependencies are pinned in `requirements.txt`, so meetings no longer silently fail to count after install (#26).

_Full history in [CHANGELOG.md](CHANGELOG.md)._
<!-- RECENT:END -->

## Everything stays local

Pulse reads files already on your disk and writes one `state.json` next to itself. No
cloud, no account, no telemetry. Your session logs never leave your machine.

## Claude sets it up

You don't configure it. Clone the repo (somewhere **outside** `~/Documents`, `~/Desktop`,
`~/Downloads`, and iCloud Drive — macOS TCC blocks the background app from reading those, so it
would crash-loop; `~/pulse` or `~/dev/pulse` is fine), open it in Claude Code, and paste:

> Read `setup/SKILL.md` and set up Pulse for me.

It discovers your paths, asks for your categories and budgets, writes your config, and
starts the menu bar app.

macOS gets the designed panel (a menu-bar card). Windows runs an always-on-top overlay.

<details>
<summary>Manual setup (without Claude Code)</summary>

1. `cp examples/config.example.yaml config.yaml` and edit the machine values (timezone, projects_dirs).
2. `cp examples/bucket-registry.example.yaml bucket-registry.yaml` and map your repo roots to categories.
3. `cp examples/appetite.example.yaml appetite.yaml` and set per-category hour budgets (or rates).
4. **macOS:** `bash install-mac.sh` — builds a repo-local `.venv` from the system
   `python3` with the pinned deps (rumps, pyyaml, pyobjc; WebKit powers the popover) and
   registers the LaunchAgent. Verify with `.venv/bin/python3 src/pulse/snapshot.py`.
   **Windows:** `pip install pyyaml`, `python3 src/pulse/snapshot.py` to verify, then `install.ps1`.
   (Clone outside `~/Documents` / `~/Desktop` / `~/Downloads` / iCloud Drive / `~/Library/CloudStorage` —
   `install-mac.sh` refuses those, as macOS TCC blocks the LaunchAgent from reading them. Run
   `bash install-mac.sh --check` to preflight a location without installing.)

</details>

## How it works

A deterministic pipeline, no LLM in the hot path: scan sessions, categorize
(`timecore`), compute per-project hours against your budgets, render the menu-bar card
from the resulting `state.json`. The repo is self-contained: `timecore`,
`scan_sessions`, and `prematch` are vendored.

## Splitting buckets & nesting groups

Two hand-edited YAML conventions let you reshape how time rolls up. Both are validated
at snapshot time — a bad edit fails loudly with a clear message instead of silently
miscounting.

**Split a bucket** (in `bucket-registry.yaml`) — carve a sub-folder out of a catch-all
category into its own bucket by adding a `children:` list. Each child gets its own
`source_path`, which **must be a subpath of its parent's** (deepest match wins, so work
under the child path lands in the child and the rest stays in the parent). The engine
already rolls child minutes up into the parent, so the parent keeps aggregating.

```yaml
buckets:
  - name: Personal
    source_path: /Users/you/personal
    children:
      - name: PulseWork
        source_path: /Users/you/personal/pulse   # must live under the parent path
```

**Nest groups** (in `appetite.yaml`) — a group's `members` list may name **other groups**
as well as engagements, so groups ladder up into a hierarchy. No new field; the tree reads
top-down. A group with a cap (`weekly_hours`/`monthly_hours`) shows a bar; a capless group
is a pure roll-up (summed hours, no bar). The menu-bar card and panel render the nesting
indented, with correct rollup totals at each level.

```yaml
groups:
  Billable:
    members: [ClientA, ClientB, ClientC]   # engagements
    weekly_hours: 32
  "Personal Software":                     # capless roll-up (no bar)
    members: [ProjectX, ProjectY]
  "All Work":                              # members name GROUPS -> nesting
    members: ["Billable", "Personal Software", Leftover]
    weekly_hours: 40
```

An engagement reachable via more than one path is counted **once**. The snapshot rejects,
loudly: an unknown member, a membership cycle, a nesting that double-counts an engagement
(reachable via a group and that group's ancestor), and a registry child whose `source_path`
is not under its parent.
