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
`bucket-registry.example.yaml`): one bucket per category, `source_path` set to the
root (use `additional_paths` for extra roots in the same category). Deepest match
wins, so a sub-folder category can live inside a parent category.

## 3. Interview — budgets
For each category, ask "how many hours per week is this worth?" Write
`appetite.yaml` (shape from `appetite.example.yaml`) using `weekly_hours`. If the
user thinks in dollars instead, offer rate mode (`monthly_value` + `target_rate`,
which derives the cap). Also set an overall `total_budget` (weekly + monthly
hours) — ask, or sum the categories.

## 4. (Optional) Cowork classification
If `cowork_dir_exists` is true, ask whether they use Claude Cowork for specific
work. If so, capture slash-command / sender-email / title→category hints into
`config.yaml`'s `cowork_classification` (shape in `config.example.yaml`). Skip if
they don't use Cowork — those sessions just won't be classified.

## 5. Write config.yaml
Copy `config.example.yaml` → `config.yaml`. Set `timezone` (ask, or infer from the
system), `projects_dirs` (from discovery; add extra dirs only if the user names
them), and `cowork_root` only if discovery found a non-default location. Leave
`timecore_dir` / `registry` / `learnings` / `rules` as the repo-local defaults
(omit them). These files (`config.yaml`, `bucket-registry.yaml`, `appetite.yaml`)
are gitignored — they hold the user's real data and never get pushed.

## 6. Install deps + verify
- `pip3 install rumps pyyaml` (macOS) or `pip install pyyaml` (Windows).
- Run `python3 snapshot.py`. Show the user the per-engagement summary it prints.
  Confirm the categories + hours look right. If a category is missing or
  mis-bucketed, revisit step 2's registry mapping and re-run.

## 7. Launch at login
- **macOS:** `bash install-mac.sh` (registers a LaunchAgent and starts the menu
  bar app).
- **Windows:** run `powershell -ExecutionPolicy Bypass -File install.ps1` (registers a
  Task Scheduler "at logon" task running the overlay with `pythonw`, and starts it now).
  The overlay is a small always-on-top window — click it to expand the breakdown, drag to
  move, right-click to quit.

## Done
Tell the user Pulse is running (macOS) or configured (Windows), and that they can
re-run `python3 snapshot.py` any time, or edit `appetite.yaml` to adjust budgets.
