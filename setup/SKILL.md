---
name: pulse-setup
description: Set up Pulse on this machine — discover paths, interview for categories + budgets, write config, install, and run a first snapshot.
---

# Pulse Setup

You are setting up Pulse for the user on THIS machine. Pulse is a menu-bar time
governor that categorizes their Claude Code activity against their work and shows
whether they're over budget on each engagement. Follow these steps in order.

## 1. Discover the machine
Run `python3 setup/discover.py` and read the JSON. It reports the OS, the Claude
Code projects dir, the Cowork sessions dir (and whether each exists), and the
user's candidate work roots ranked by session count.

If `projects_dir_exists` is false, stop and tell the user Pulse needs Claude Code
session history to work.

## 2. Interview — categories
Show the user the top candidate roots (path + session count). Ignore obvious noise
(e.g. `/private/tmp`, `/`). Ask them to group the ones they want tracked into
**categories** (their clients/projects/areas). A category can map to one or more
roots. Example: "everything under `~/work/acme` → category `Acme`." Roots they
don't care about are skipped.

Write these into `bucket-registry.yaml` (copy the shape from
`examples/bucket-registry.example.yaml`): one bucket per category, `source_path` set to the
root (use `additional_paths` for extra roots in the same category). Deepest match
wins, so a sub-folder category can live inside a parent category.

## 3. Interview — budgets
For each category, ask "how many hours per week is this worth?" Write
`appetite.yaml` (shape from `examples/appetite.example.yaml`) using `weekly_hours`. If the
user thinks in dollars instead, offer rate mode (`monthly_value` + `target_rate`,
which derives the cap). Also set an overall `total_budget` (weekly + monthly
hours) — ask, or sum the categories.

## 4. (Optional) Cowork classification
If `cowork_dir_exists` is true, ask whether they use Claude Cowork for specific
work. If so, capture slash-command / sender-email / title→category hints into
`config.yaml`'s `cowork_classification` (shape in `examples/config.example.yaml`). Skip if
they don't use Cowork — those sessions just won't be classified.

## 5. (Optional) Calendar
Pulse can count meeting time toward each engagement. It does **not** run its own
login — it reuses existing Google OAuth credential files (the kind
`google_workspace_mcp` writes, or a hand-rolled integration). Discovery's
`calendar_cred_candidates` lists any it found by shape (a `*.json` with a token)
under `~/.google_workspace_mcp`.
- If candidates were found, show their tags and ask which (if any) to wire in.
- **Do NOT assume the user has none when the list is empty** — many people (e.g.
  hand-rolled GWS setups) keep creds in a custom dir. Ask whether they have a
  credentials directory elsewhere; if they give a path, validate it with
  `python3 -c "import sys; sys.path.insert(0,'setup'); import discover; print(discover.validate_cred_dir('<path>'))"`
  before using it.
- For each account they want, note `{tag: <short label>, credentials_dir: <path>}`
  and ask for their own email address(es) (so they're filtered out of co-attendee
  counts). These get written in step 6.
- If they have no creds and don't want to set any up, leave calendar empty — Pulse
  runs sessions + Cowork only, and they can add it later by editing `config.yaml`.

## 6. Write config.yaml
Copy `examples/config.example.yaml` → `config.yaml`. Set `timezone` (ask, or infer from the
system), `projects_dirs` (from discovery; add extra dirs only if the user names
them), and `cowork_root` only if discovery found a non-default location. If the user
wired calendar in step 5, set `calendar.accounts` (each `{tag, credentials_dir}` —
use a home-relative path when it's under home, matching the example) and
`calendar.self_emails`; otherwise leave them empty. Leave
`timecore_dir` / `registry` / `learnings` / `rules` as the repo-local defaults
(omit them). These files (`config.yaml`, `bucket-registry.yaml`, `appetite.yaml`)
are gitignored — they hold the user's real data and never get pushed.

## 7. Install
- **macOS:** `bash install-mac.sh`. It builds a repo-local `.venv` from the system
  `python3` with the pinned deps (rumps, pyyaml, pyobjc — WebKit powers the designed
  popover panel), registers the LaunchAgent, and starts the app. The venv keeps the
  install-time and runtime interpreter identical, so the app can't crash-loop on a
  missing module. The clone must live outside `~/Documents` / `~/Desktop` /
  `~/Downloads` / iCloud Drive / `~/Library/CloudStorage` (macOS TCC blocks the
  LaunchAgent from reading those) — the installer refuses them; `bash install-mac.sh
  --check` preflights a location without installing.
- **Windows:** `pip install pyyaml`, then `powershell -ExecutionPolicy Bypass -File install.ps1`
  (registers a Task Scheduler "at logon" task running the overlay with `pythonw`, and starts it
  now). The overlay is a small always-on-top window — click it to expand the breakdown, drag to
  move, right-click to quit.

## 8. Verify
- Run `.venv/bin/python3 src/pulse/snapshot.py` (macOS) or `python3 src/pulse/snapshot.py`
  (Windows). Show the user the per-engagement summary it prints. Confirm the categories +
  hours look right. If a category is missing or mis-bucketed, revisit step 2's registry
  mapping and re-run.

## Done
Tell the user Pulse is running (macOS) or configured (Windows), and that they can
re-run `python3 src/pulse/snapshot.py` any time, or edit `appetite.yaml` to adjust budgets.

**Tell them explicitly: meetings are NOT counted yet.** Pulse currently tracks
Claude Code sessions + Cowork only. To also count calendar time, they can add a
`calendar` block to `config.yaml` later (Google Calendar via OAuth — see
`examples/config.example.yaml`). It's off by default and needs their own credentials, so
don't set it up in this session unless they ask.
