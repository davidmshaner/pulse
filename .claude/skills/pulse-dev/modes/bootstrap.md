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
> `https://github.com/users/shanerconsulting/projects/1`), Status = the **6 stages** below, the
> five labels exist, **all open issues AND open PRs are backfilled** (issues → Backlog, PRs → In
> Review), `board_number: 1` is in `context/board-config.json`, and the auto-add workflow is
> committed at `.github/workflows/project-sync.yml`. **Remaining manual step:** create the
> `ADD_TO_PROJECT_PAT` secret (Step 2a) and enable the built-in advancement toggles (Step 2b). The
> steps below are the reusable procedure (and the recipe for the next port).

## What the board must look like (the target state)
1. A **GitHub Project** named "Pulse", owner `shanerconsulting`, with a **Status** field whose
   options are the **same 6 stages as every harness board** (this is the canonical column set;
   match it exactly, do not trim it for a "lean" project — the columns are the universal work-item
   lifecycle, independent of which process *stages* a project runs):
   **Backlog → Up Next → In Progress → In Review → QA → Done.**
2. Five **type labels** on `shanerconsulting/pulse`: `bug` · `feature` · `enhancement` · `chore` ·
   `tech-debt`.
3. The `shanerconsulting` gh token carries the **`project`** scope.
4. **Auto-add:** new issues **and PRs** land on the board automatically.
5. **Card advancement:** issue closed / PR merged → **Done** (Up Next / In Review / QA moves stay
   human + work-mode — see the note below).
6. Every **existing open issue AND open PR** is on the board (backfill — PRs too, not just issues).
7. The board number recorded in `context/board-config.json` (intake + work-mode read it).

## Step 1 — board + the 6-stage Status + labels + scope
```bash
gh auth switch --user shanerconsulting >/dev/null 2>&1   # board ops run under this account
# project scope (one-time; gh auth refresh has NO --user, so switch first, then refresh in a REAL
# terminal — the device/browser flow needs a TTY): gh auth refresh -h github.com -s project

# create the board if none exists (prints the new NUMBER + the Status field id)
gh project list --owner shanerconsulting --format json --jq '.projects[] | "\(.number)  \(.title)"'
gh project create --owner shanerconsulting --title "Pulse"

# the five type labels (--force is idempotent)
for L in bug feature enhancement chore tech-debt; do gh label create "$L" --repo shanerconsulting/pulse --force; done
```
A new project's Status is `Todo / In Progress / Done`. Replace it with the **canonical 6 stages**
via GraphQL (do this while the board is empty, or re-assign items after — replacing options mints
new option ids and orphans existing assignments):
```bash
FID=$(gh project field-list <N> --owner shanerconsulting --format json --jq '.fields[]|select(.name=="Status").id')
gh api graphql -f query='
mutation($fid:ID!){ updateProjectV2Field(input:{ fieldId:$fid, singleSelectOptions:[
    {name:"Backlog", color:GRAY, description:""},
    {name:"Up Next", color:BLUE, description:""},
    {name:"In Progress", color:YELLOW, description:""},
    {name:"In Review", color:ORANGE, description:""},
    {name:"QA", color:PURPLE, description:""},
    {name:"Done", color:GREEN, description:""}
  ]}){ projectV2Field{ ... on ProjectV2SingleSelectField { options{ id name } } } } }' -f fid="$FID"
```
Record the project **number** in `context/board-config.json` (`board_number`), and keep the printed
option ids handy for Step 3 (Backlog + In Review) and for work-mode card moves.

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
    env:
      PAT: ${{ secrets.ADD_TO_PROJECT_PAT }}   # `secrets` is NOT allowed in `if:` (it makes the
                                               # whole file invalid → every push fails at parse
                                               # time and emails a failure). Map to env, gate on env.
    steps:
      - if: ${{ env.PAT != '' }}               # skips cleanly until the PAT secret exists — no failed runs
        uses: actions/add-to-project@v1.0.2
        with:
          # users: https://github.com/users/<owner>/projects/<N> · orgs: https://github.com/orgs/<owner>/projects/<N>
          project-url: https://github.com/orgs/shanerconsulting/projects/<N>
          github-token: ${{ env.PAT }}
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

## Step 3 — backfill existing issues AND PRs
**Every open issue and every open PR must be on the board** — `gh issue list` excludes PRs, so
backfill both. Issues → Backlog, open PRs → In Review (an open PR is mid-review by definition).
```bash
PROJ=<project-id>; FID=<status-field-id>; BACKLOG=<backlog-opt-id>; INREVIEW=<in-review-opt-id>
# issues -> Backlog
gh issue list --repo shanerconsulting/pulse --state open --json url --jq '.[].url' | while read U; do
  ITEM=$(gh project item-add <N> --owner shanerconsulting --url "$U" --format json --jq '.id')
  gh project item-edit --id "$ITEM" --project-id "$PROJ" --field-id "$FID" --single-select-option-id "$BACKLOG"
done
# PRs -> In Review
gh pr list --repo shanerconsulting/pulse --state open --json url --jq '.[].url' | while read U; do
  ITEM=$(gh project item-add <N> --owner shanerconsulting --url "$U" --format json --jq '.id')
  gh project item-edit --id "$ITEM" --project-id "$PROJ" --field-id "$FID" --single-select-option-id "$INREVIEW"
done
gh auth switch --user <prior-account> >/dev/null 2>&1
```
Going forward the auto-add workflow (2a) keeps new issues + PRs on the board; David triages Backlog
items to Up Next.

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
