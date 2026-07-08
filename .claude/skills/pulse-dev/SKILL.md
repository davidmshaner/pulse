---
name: pulse-dev
description: >
  The Pulse development process, end to end — one skill for the whole loop. Use when David says
  "work the next Pulse issue", "work on Pulse #<n>", "run the Pulse board", "file a Pulse issue /
  log a Pulse bug", "QA Pulse / run the app", "tail the other Pulse agent", or "set up the Pulse
  board". Pulse is a single-user macOS menu-bar app (Python/rumps, shanerconsulting/pulse) that
  measures billable Claude Code time across projects. Five modes — default = pick + work an issue
  to a merged PR; --issue = file a contextualized issue; --qa = run the real app and read the
  menu-bar card; --tail = coordinate with a parallel worktree agent; --bootstrap = provision the
  GitHub board + labels + automations. This SKILL.md is the outline; detail lives in modes/ + process/.
---

# /pulse-dev — Pulse Development

This skill **is** the Pulse development process. Filing an issue, working one, QA-ing the app,
coordinating with a parallel agent, and setting up the board are **modes of one process**.

- **superpowers is the coding harness of choice.** Engineering craft (brainstorm → spec → plan →
  TDD → review) is delegated to superpowers skills. This process encodes only Pulse-specific
  judgment: how work is captured, isolated, gated, and merged.
- **Pulse is a local macOS app run from source** (`shanerconsulting/pulse`, Python/rumps menu bar,
  installed as a LaunchAgent), now used by **a few external users who update via `git pull`**. It
  ships to no store or service, so there is **no deploy** — but there IS a light release track: a
  behavior change adds a `CHANGELOG.md` entry, and a release bumps `VERSION` + tags `vX.Y.Z` + cuts
  a GitHub Release (runbook in `CONTRIBUTING.md`). For most work a merge to `main` (+ relaunch) is
  still the end; cutting a release is a deliberate, separate step.
- **Account:** all GitHub work (board, issues) runs under **`shanerconsulting`** — switch to it for
  gh board/issue ops and restore your prior account after (the intake script does this for you).
- **Generic version:** `knowledge/autonomous-development-harness.md` in the Shaner Consulting repo
  is the GI-agnostic spine this instantiates. This is the **lean** port (like `/shorty-dev`):
  intake + work + QA + light concurrency + board bootstrap; nothing else.

## Modes (entry points)

| Invocation | Mode | What it does | Detail |
|---|---|---|---|
| `/pulse-dev` · "work the next issue" · "work on #n" | **work** (default) | pick an In-Progress issue → ship to a merged PR | `modes/work.md` |
| `/pulse-dev --issue` · "file a Pulse issue" | **issue** | raw ask → contextualized issue in Backlog | `modes/issue.md` |
| `/pulse-dev --qa` · "QA Pulse" · "run the app" | **qa** | run the real app, read the menu-bar card | `modes/qa.md` |
| `/pulse-dev --tail` · "tail the other agent" | **tail** | read a parallel worktree agent to coordinate | `modes/tail.md` |
| `/pulse-dev --prep` · "stage the wave" · "prep the board" | **prep** | grade + stage + sequence the backlog so Up Next is fire-ready for a multi-agent run | `modes/prep.md` |
| `/pulse-dev --bootstrap` | **bootstrap** | provision the board + labels + auto-add + advancement automations | `modes/bootstrap.md` |

## Trigger / End State
- **Trigger:** a bug, feature, enhancement, chore, or tech-debt item exists and should be tracked.
- **End State:** a contextualized issue, executed on an isolated branch/worktree, **`pytest`
  green**, QA'd by running the actual app and reading the menu-bar card, merged to `main` via a
  reviewed PR with `Closes #<n>`, the board item in **Done**, the worktree removed.

## How the spine maps to Pulse
| Generic spine step | Pulse | Lives in |
|---|---|---|
| 1. Intake | Capture (`--issue`) → Backlog | `modes/issue.md` |
| 2. Triage (human) | Backlog → Up Next | David promotes |
| 3. Execution | Up Next → In Progress + Build (superpowers) | `modes/work.md` |
| 4. Pre-release QA (FAR boundary) | `pytest` gate **+ run the real app** | `modes/work.md` + `modes/qa.md` |
| 5. Review and merge | review (`/code-review`) → merge | `modes/work.md` |
| 6. Release | light — most merges end at `main` (+ relaunch); a release bumps `VERSION` + tags `vX.Y.Z` + cuts a GitHub Release | `CONTRIBUTING.md` |
| 7. Validation / distribution | external users update via `git pull`; no store/installer distribution | `CONTRIBUTING.md` |
| 8. Compounding feedback | feed `--issue` when a pickup needed context it lacked | `modes/work.md` |

> Pulse has a **far QA boundary**: you run the real app locally (or reinstall the LaunchAgent), so
> pre-release QA does all the work and there is no post-release validation stage.

## The loop (scannable)

> **Board columns (the same 6 as every harness board):** Backlog → Up Next → In Progress → In
> Review → QA → Done. Provisioned by `--bootstrap`; every issue AND every PR lives on the board.

**Capture** (`--issue`) — raw ask → an issue rich enough for a cold agent to run without asking.
Cite `src/pulse/` + `tests/` code as `path:line`, name the area, dedup, classify with one type
label, land in **Backlog**. *Gate:* labeled issue on the board. → `modes/issue.md`

**Triage** — David moves Backlog → **Up Next** (the ready queue). *Gate:* card on Up Next.

**Isolate** — work-mode picks from Up Next, moves the card to **In Progress** as its first action,
then one worktree per issue: `git worktree add .worktrees/issue-<n> -b issue-<n>` (Pulse keeps
worktrees under the gitignored `.worktrees/`). Parallel agents each take a distinct issue. →
`modes/work.md`

**Build** — run the superpowers stack as the work warrants: `brainstorming` (if design is open) →
`writing-plans` → `test-driven-development`. Small fixes can skip to a failing test + fix. →
`modes/work.md`

**Gate (QA)** — **`pytest` must be green** (run from repo root), **and** run the real app and read
the menu-bar card to verify the change on the actual user path. *Gate:* tests green + app
exercised. → `modes/qa.md`

**PR → In Review → QA → Done** — open a PR against `main` (`Closes #<n>`) and move the card to **In
Review**; review with `/code-review` or a review subagent. Run the app (`--qa`) and move to **QA**.
Merge → card to **Done** → `git worktree remove .worktrees/issue-<n>`. *Gate:* merged, worktree
gone. → `modes/work.md`

**Compounding feedback** — if the pickup needed context the issue should have carried, make a
narrow edit to `modes/issue.md` (Enrich step). → `modes/work.md`

## Cross-cutting
- **Concurrency (thin).** Parallel agents take distinct issues in distinct worktrees, so they
  rarely collide — but before merging, re-fetch and confirm your diff is only your files; if
  another agent is live, read it first. → `modes/tail.md`
- **Known issues.** The Pulse traps (rumps disabled-gray menu items without a callback; the
  Python.app process-kill caveat; the borderless-overlay rendering quirk) live in
  `process/conventions.md` — cite any the work risks tripping.

## Reference (process/ + bootstrap)
- `process/conventions.md` — how to run/gate (pytest, LaunchAgent), branch+PR+worktree discipline,
  the shanerconsulting account rule, and the known-issues list.
- `modes/bootstrap.md` — provision the board + columns + labels + `project` scope + **auto-add and
  card-advancement automations** + backfill existing issues. Run it when porting to a fresh project
  or to verify the board + automations are intact.

## Scripts
- `scripts/pulse_issue.py` — deterministic issue creation + board placement for **issue** mode.
