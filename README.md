# Pulse

**Know where your time actually went.**

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

## Everything stays local

Pulse reads files already on your disk and writes one `state.json` next to itself. No
cloud, no account, no telemetry. Your session logs never leave your machine.

## Claude sets it up

You don't configure it. Clone the repo, open it in Claude Code, and paste:

> Read `setup/SKILL.md` and set up Pulse for me.

It discovers your paths, asks for your categories and budgets, writes your config, and
starts the menu bar app.

macOS gets the designed panel (a menu-bar card). Windows runs an always-on-top overlay.

<details>
<summary>Manual setup (without Claude Code)</summary>

1. `pip3 install rumps pyyaml pyobjc-framework-WebKit` (macOS) or `pip install pyyaml` (Windows).
2. `cp config.example.yaml config.yaml` and edit the machine values (timezone, projects_dirs).
3. `cp bucket-registry.example.yaml bucket-registry.yaml` and map your repo roots to categories.
4. `cp appetite.example.yaml appetite.yaml` and set per-category hour budgets (or rates).
5. `python3 snapshot.py` to verify, then `bash install-mac.sh` to run it at login.

</details>

## How it works

A deterministic pipeline, no LLM in the hot path: scan sessions, categorize
(`timecore`), compute per-project hours against your budgets, render the menu-bar card
from the resulting `state.json`. The repo is self-contained: `timecore`,
`scan_sessions`, and `prematch` are vendored.
