# `/pulse-dev --bootstrap` — Provision the Board + Automations

> Mode of `/pulse-dev` (see `../SKILL.md`). Part of bootstrapping the harness is standing up a
> tracker that the rest of the loop can write to **and that keeps itself current**. This mode
> **verifies or creates** the GitHub Project board, the type labels, the `project` token scope, the
> **auto-add + card-advancement automations**, and **backfills existing issues**. Idempotent: run it
> on a fresh project to set everything up, or on an existing one to confirm it's intact.
>
> **`--bootstrap` is the first thing you run when porting the harness to a new project** — `--issue`
> can't place a card until the board exists and its number is in `context/board-config.json`.

All GitHub work here runs under the **`shanerconsulting`** account (switch to it, restore after).

> **Provisioned state (Pulse, 2026-06-13):** board **#1** exists (user `shanerconsulting`,
> `https://github.com/users/shanerconsulting/projects/1`), Status = Backlog/In Progress/Done, the
> five labels exist, all open issues are backfilled into Backlog, `board_number: 1` is in
> `context/board-config.json`, and the auto-add workflow is committed at
> `.github/workflows/project-sync.yml`. **Remaining manual step:** create the `ADD_TO_PROJECT_PAT`
> secret (Step 2a) and enable the built-in advancement toggles (Step 2b). The steps below are the
> reusable procedure (and the recipe for the next port).

## What the board must look like (the target state)
1. A **GitHub Project** named "Pulse", owner `shanerconsulting`, with a **Status** field whose
   options are **Backlog → In Progress → Done**.
2. Five **type labels** on `shanerconsulting/pulse`: `bug` · `feature` · `enhancement` · `chore` ·
   `tech-debt`.
3. The `shanerconsulting` gh token carries the **`project`** scope.
4. **Auto-add:** new issues + PRs land on the board automatically.
5. **Card advancement:** issue closed / PR merged → **Done** (in-progress moves stay human/work-mode
   at pickup — see the note below).
6. Every **existing open issue** is on the board (backfill).
7. The board number recorded in `context/board-config.json` (intake + work-mode read it).

## Step 1 — board + columns + labels + scope
```bash
gh auth switch --user shanerconsulting >/dev/null 2>&1
# project scope (one-time; opens a browser consent)
gh auth status 2>&1 | grep -A3 shanerconsulting | grep -q "project" || gh auth refresh -s project --user shanerconsulting

# create the board if none exists, then add In Progress / Done to the Status field
gh project list --owner shanerconsulting --format json --jq '.projects[] | "\(.number)  \(.title)"'
gh project create --owner shanerconsulting --title "Pulse"     # prints the new NUMBER
# (Status starts with Todo/In Progress/Done; rename/ensure Backlog/In Progress/Done via the UI or
#  `gh project field-list <N> --owner shanerconsulting` + field edits)

# the five type labels (--force is idempotent)
for L in bug feature enhancement chore tech-debt; do
  gh label create "$L" --repo shanerconsulting/pulse --force
done
```
Record the printed project **number** in `context/board-config.json` (`board_number`).

## Step 2 — automations (BOTH a committed Action and the built-in toggles)

### 2a. Committed Actions workflow (reproducible, version-controlled)
`.github/workflows/project-sync.yml` is committed in this repo — it auto-adds every new issue/PR to
the board (the add step is `if`-guarded on the secret, so it skips cleanly until the PAT exists). The
shape, for the next port:
```yaml
name: project-sync
on:
  issues:        { types: [opened, reopened, transferred] }
  pull_request:  { types: [opened, reopened, ready_for_review] }
jobs:
  add-to-project:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/add-to-project@v1.0.2
        with:
          # users: https://github.com/users/<owner>/projects/<N> · orgs: https://github.com/orgs/<owner>/projects/<N>
          project-url: https://github.com/orgs/shanerconsulting/projects/<N>
          github-token: ${{ secrets.ADD_TO_PROJECT_PAT }}
```
**One manual step (can't be done headlessly):** create a fine-grained PAT with **Projects: read/write
+ Issues: read** scope and store it as the repo secret **`ADD_TO_PROJECT_PAT`**
(`gh secret set ADD_TO_PROJECT_PAT --repo shanerconsulting/pulse` after generating it in the browser).
Until that secret exists the workflow no-ops; the built-in toggles (2b) cover the gap immediately.

### 2b. Built-in Project workflows (UI toggles — belt-and-suspenders + advancement)
In the Project → **⋯ → Workflows**, enable:
- **Item added to project → set Status = `Backlog`** (so auto-added items default to Backlog).
- **Item closed → set Status = `Done`** (covers issues closed and PRs).
- **Pull request merged → set Status = `Done`**.
- (optional) **Auto-archive items** when closed > 2 weeks.

These built-ins need **no PAT** and work immediately; the committed Action (2a) is what makes the
setup reproducible on the next port. **In Progress is not auto-set on PR-open** (GitHub has no clean
built-in for it) — that move stays the human triage (Backlog → In Progress) or work-mode's pickup
move. Document it; don't fake it.

## Step 3 — backfill existing issues
Add every open issue already in the repo onto the new board:
```bash
gh issue list --repo shanerconsulting/pulse --state open --json url --jq '.[].url' | while read U; do
  gh project item-add <N> --owner shanerconsulting --url "$U"
done
gh auth switch --user <prior-account> >/dev/null 2>&1
```
New items land in Backlog (per 2b); David triages them to In Progress.

## board-config.json (what intake + work-mode read)
```json
{ "account": "shanerconsulting", "repo": "shanerconsulting/pulse",
  "project_owner": "shanerconsulting", "board_number": <N>,
  "status_field": "Status", "status_value": "Backlog" }
```

## Porting this to a new project (the generalizable bit)
This mode is the first step of any harness port: pick the repo + account, create the board + Status
options, create the project's type labels, grant `project` scope, **commit the auto-add Action +
enable the advancement toggles**, backfill existing issues, and write the new `board-config.json`.
Everything downstream (intake placement, work-mode picks, the on-merge → Done advance) reads from
there. The same shape stamps onto `/gi-dev`, `/shorty-dev`, and the next port.

## Scope
Provision + verify the tracker and its automations only. It does not file or move individual issues
through the loop — that is `--issue` and the work mode.
