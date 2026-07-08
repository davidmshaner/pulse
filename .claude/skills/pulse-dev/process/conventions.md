# Pulse Conventions & Known Issues

> Reference for `/pulse-dev` (see `../SKILL.md`). The Pulse-specific judgment the modes assume: how
> to run/gate, the branch + account discipline, and the traps not to re-diagnose.

## Build / run / gate
- **Gate:** run pytest with the repo's **`.venv`** interpreter, not bare `python3` —
  `.venv/bin/python3 -m pytest -q` from the repo root must be green. Never claim done without it.
  (Bare `python3` is often Homebrew's, which lacks `pyyaml`/`pyobjc`; `config.py` then `sys.exit(2)`s
  on import — "MISSING_DEPS" / `SystemExit: 2` — and the whole suite fails to collect. That's a
  wrong-interpreter error, not a code failure.)
- **Running tests in a `.worktrees/issue-<n>` worktree:** the worktree has no `.venv` and none of the
  gitignored user data, so use the main checkout's venv and symlink the data files in once:
  ```bash
  for f in config.yaml appetite.yaml; do ln -s ../../$f $f; done   # gitignored; never committed
  ../../.venv/bin/python3 -m pytest -q
  ```
- **Run (foreground)** for a quick look: `python3 src/pulse/app.py` (Ctrl-C to stop).
- **Run (installed)** — the shipped path is a per-user **LaunchAgent** (`com.pulse.menubar`):
  ```bash
  ./install-mac.sh                                   # (re)install + start; builds .venv from requirements.txt
  launchctl kickstart -k "gui/$(id -u)/com.pulse.menubar"   # restart after a code change
  ```
- **Logs:** `.cache/pulse.stdout.log` / `.cache/pulse.stderr.log`. A rumps app that dies on launch
  shows the traceback there.
- **State / config:** `state.json`, `config.yaml`, `appetite.yaml` (per-project budgets) at the repo
  root; `src/pulse/config.py` owns `PKG_DIR` / `DATA_DIR`.
- **Deps:** `rumps`, `pyyaml`, `pyobjc` (the WebKit popover panel), pinned in `requirements.txt`.
  `install-mac.sh` builds a repo-local **`.venv`** from `/usr/bin/python3` and installs them there,
  and the LaunchAgent runs `.venv/bin/python3` — so install-time and runtime share one interpreter
  (issue #15; do not revert to a `--user` system-python install).

## Branch + account discipline
- **Every change is branch + PR + worktree** — no direct commits to `main`. One worktree per issue
  under the gitignored `.worktrees/`: `git worktree add .worktrees/issue-<n> -b issue-<n>`; remove
  with `git worktree remove .worktrees/issue-<n>` after merge.
- **Account: `shanerconsulting`.** The repo remote is `shanerconsulting/pulse`. Push with `git
  pushx` (it selects the shanerconsulting account and restores yours after). For `gh` board/issue
  ops, switch to `shanerconsulting` and restore your prior account — the intake script does this for
  you; do it by hand for ad-hoc `gh issue`/`gh project` calls.

## Known issues — do NOT re-diagnose
Settled traps. When the work risks one, cite it in the issue/PR rather than rediscovering it:
- **rumps disabled-gray menu items.** A `rumps.MenuItem` created **without a callback** renders as
  disabled-gray on macOS. For an info-only row (a value you just want to display), attach a **no-op
  callback** so it renders normal, not grayed.
- **Killing the app process.** `pkill -f "app.py"` can miss the running rumps process when it's
  hosted under **Python.app** (the launcher renames the process). Prefer `launchctl bootout
  "gui/$(id -u)/com.pulse.menubar"` for the installed agent, or match the actual process name before
  trusting a `pkill`.
- **Borderless overlay rendering** (issue #11) — the macOS borderless overlay has a deferred
  rendering quirk; don't re-chase it as new.
- **Privacy / session data is sensitive.** Pulse reads Claude Code session JSONL; never log or commit
  raw session content or paths that leak client names (issue #8 was a privacy scrub + history
  rewrite). Scrub before committing fixtures or logs.
- **docs/ is tracked (since #43) but the repo is PUBLIC.** Specs/plans land in `docs/specs/` /
  `docs/plans/` and MUST be scrubbed — no client names, rates, or dollar figures. Five legacy
  pre-public design docs carry real client billing data and are explicitly gitignored; never
  `git add -f` them or drop their ignore entries.

## Explicitly NOT part of this process
No release tracks, no marketplace/deploy, no milestones-as-queue, no version-bump ceremony, no
distribution substages, no cost gate (Pulse makes no metered API calls). Pulse is a local single-user
app, so a merge to `main` (and a relaunch to pick up changes) is the end. The generic spine this
instantiates is `knowledge/autonomous-development-harness.md`; the GI instance is `/gi-dev`, the
sibling local-app instance is `/shorty-dev`.
