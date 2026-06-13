# `/pulse-dev --qa` — Run the App, Read the Menu-Bar Card

> Mode of `/pulse-dev` (see `../SKILL.md`). Pulse has a **far QA boundary**: the real app runs
> locally, so QA means actually running it and reading the menu-bar card — not trusting `pytest`
> alone. This mode is both a standalone entry point ("QA Pulse") and the closing gate of `work.md`
> step 4.

## 1. Tests first (necessary, not sufficient)
```bash
python3 -m pytest -q          # from the repo root
```
Must be green. Green tests prove the time-accounting and rendering logic hold; they do **not** prove
the menu-bar card looks right or that the LaunchAgent runs clean. That is what the run is for.

## 2. Run the real app
```bash
# foreground (fastest for a look; Ctrl-C to stop):
python3 src/pulse/app.py
# or reinstall the LaunchAgent to test the shipped path (survives terminal close):
./install-mac.sh
```
- **Logs:** `.cache/pulse.stdout.log` / `.cache/pulse.stderr.log` (LaunchAgent), or stdout
  (foreground). A rumps app that dies on launch usually shows the traceback here.
- **State / config:** `state.json` and `config.yaml` / `appetite.yaml` (the per-project budgets) at
  the repo root; inspect when a change touches accounting or budgets.
- **Restart the installed agent** after a code change: `launchctl kickstart -k
  "gui/$(id -u)/com.pulse.menubar"` (the LaunchAgent label is `com.pulse.menubar`).

## 3. Read the menu-bar card (the user path)
Pulse lives in the menu bar; the card is the whole user surface. Exercise what your change touches:
- **The card** — time split across projects, the active project, over-budget shown in **red**.
  Confirm the split is honest (active-typing time, not session length), the project attribution is
  right (work done in another project's folder counts to the right project), and meetings show up.
- **The popover panel** (WebKit-rendered) — the designed detail view; check layout/rendering,
  especially after any `frontend_common.py` / `app_win.py` / HTML-render change.
- **Background accounting** (no UI) — session scan, cowork scan, live bucketing, snapshotting.
  Verify via `state.json` and the logs, not the card.

Capture the real artifact as evidence for anything user-visible (a screenshot of the card/popover,
or the relevant `state.json` rows).

## 4. Verdict
- **Pass** → the change works on the real path; record what you ran + saw. In `work.md` this
  unblocks the PR.
- **Fail** → not done; fix it (root-cause via `superpowers:systematic-debugging` for a defect, no
  symptom patches) and re-run. If it's a new recurring trap, add it to `../process/conventions.md`
  "Known issues".

## Scope
Run + observe. This mode does not merge or move the board — `work.md` owns those. Run it standalone
to sanity-check the app, or as `work.md`'s gate before a PR.
