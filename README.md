# Pulse

An always-visible menu-bar attention-budget governor. It reads your Claude Code
session activity (and Claude Cowork), categorizes time against your engagements,
and answers "should I stop working on this right now?" — not "how did my week go?".

macOS today (rumps menu bar); a Windows overlay is in progress.

## Setup
Pulse is designed to be set up by Claude Code. Open this repo in Claude Code and
run the setup (a guided setup skill ships in the next release). Until then, manual:

1. `pip3 install rumps pyyaml`
2. `cp config.example.yaml config.yaml` and edit the machine values (timezone, projects_dirs).
3. `cp bucket-registry.example.yaml bucket-registry.yaml` and map your repo roots to categories.
4. `cp appetite.example.yaml appetite.yaml` and set per-category hour budgets (or rates).
5. `python3 snapshot.py` to verify, then `bash install-mac.sh` to run it at login.

## How it works
A deterministic pipeline (no LLM in the hot path): scan sessions -> categorize
(`timecore`) -> compute per-engagement hours vs caps -> paint the menu bar.
The repo is self-contained: `timecore`, `scan_sessions`, and `prematch` are vendored.
