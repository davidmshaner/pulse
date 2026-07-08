# `/pulse-dev --prep` — Stage the Wave

> Mode of `/pulse-dev` (see `../SKILL.md`). Prepare the backlog for a **multi-agent run** —
> several agents each taking a card in its own worktree at once. The job is to make one sentence
> true before any window opens:
>
> > **Everything in Up Next is fire-ready, collision-checked, and in a safe wave order.**
>
> A multi-agent run picks from Up Next *blindly*, so Up Next has to earn that trust. This mode is
> the prep loop that earns it. It does NOT implement cards (that's `work` mode) — it grades,
> stages, sequences, and reshapes the board.

## When to run

Before spinning up parallel windows to burn down the backlog; after a batch of merges (the board
has drifted); or any time you want to know "what can I actually fire right now."

## The three gates

Every card is graded against these. A card "in Up Next" that fails any gate is a trap — it looks
ready and isn't.

1. **Readiness ("rightness").** Can a *cold* agent run it to a PR **without asking a question?**
   Read the body. It FAILS if it names an unresolved design fork, says "needs new machinery,"
   depends on a decision not yet made, or has a subjective acceptance criterion. A *bounded* fork
   whose acceptance criteria accept either branch still passes. Column is irrelevant — readiness
   is a property of the issue body, not where it sits.
2. **Isolation.** Do any two *ready* cards touch the same files/neighborhood? Pulse's hot
   neighborhoods: **panel/render** (`panel/template.html`, `panel/render_state.py`,
   `frontend_common.py`); **snapshot caps/groups** (`snapshot.py` engagement_caps/group_blocks +
   `frontend_common.py`); **scanners** (`scan_sessions.py`, `scan_cowork.py`); **classifier**
   (`timecore/classify.py`, `prematch.py`). Two cards in one neighborhood **cannot fire in the
   same wave** — they collide at merge even from separate worktrees.
3. **Review/merge capacity.** One `main`, one human. N PRs serialize at the merge queue and each
   wants `/code-review` + a real QA pass (run the actual app). Don't queue more than can be
   shepherded.

## Flow

### 1. Snapshot the live board — never trust memory
Pull **every open issue and its column**, and the full board item set, then reconcile. Cards move
under you between sessions. Always re-read immediately before prepping, and again before merging.
```bash
gh auth switch --user shanerconsulting >/dev/null 2>&1   # board ops need this account
gh issue list --repo shanerconsulting/pulse --state open --limit 100 \
  --json number,title,labels,projectItems
```
Board identifiers (Pulse board #1, owner `shanerconsulting` — a *user* project, so GraphQL goes
through `user(login:...)`, not `--owner` on `field-list`):
```
PROJ  PVT_kwHOD5-wHs4Bak8f
FID   PVTSSF_lAHOD5-wHs4Bak8fzhVbjRw   (Status)
OPTS  Backlog 29b6dece · Up Next ff757a65 · In Progress 886bb936
      In Review 6f15eaf5 · QA 84960802 · Done 38e407d5
```

### 2. Hygiene sweep — both directions
The board carries **PRs and closed cards**, not just open issues. Sweep both directions via
GraphQL (`user(login:"shanerconsulting"){ projectV2(number:1){ items(...) } }` with issue/PR
`state` + Status):
- **Open-but-off-board:** any open issue with no Pulse project item never got placed — add it.
- **Done-but-not-in-Done:** any item whose issue is `CLOSED` / PR is `MERGED` but whose column is
  not Done — move it to Done.
- **In-flight, hands-off:** anything in In Progress / In Review / QA whose issue/PR is still open
  is claimed by another agent — leave it (see `tail.md`).
- **Dirty main checkout:** uncommitted changes in the main worktree are unfiled work — flag them
  to David (file an issue + branch, or he claims them). Every change is branch + PR
  (`process/conventions.md`).

### 3. Grade every card against the three gates, sort into buckets
- **Ready & fire-now** — passes Gate 1, no unresolved dependency, no wave collision.
- **Ready but held** — passes Gate 1 but collides with a fired card or needs another card first.
- **Not ready → needs staging** — fails Gate 1.
- **Blocked on external** — needs hardware/humans this machine doesn't have (e.g. the Windows
  cards #6/#9 need a Windows box + Bonner). Not agent-fireable; leave in Backlog, note the
  unblock.

### 4. Stage the not-ready cards (turn red → green) — the high-leverage part
- **Hunt for a keystone first.** Cards that share *one* underlying decision ripen together —
  resolve it once (e.g. two cards that both evolve the `appetite.yaml` schema are really one
  design call).
- **Match the work to the blocker:** `superpowers:brainstorming` for a design-open fork; a
  **session with David** for taste calls (config-schema UX is his taste — he hand-edits the
  YAML); a **spike** for genuine R&D.
- **The staging OUTPUT is bounded:** (a) a short design doc under `docs/` recording the decision
  so each per-card agent **inherits** it, and (b) enriched issue bodies — decided approach +
  acceptance criteria + dependencies. **Stop there.** Do NOT write full implementation plans —
  each agent self-plans in its worktree.

### 5. Sequence into waves
Dependency order first, then spread by neighborhood (one card per hot-file cluster per wave).
**Hold wave-2+ cards in Backlog, not Up Next**, so a blind fire can't grab them early; promote
them when their blocker merges.

### 6. Reshape the board so Up Next == exactly the fire-now set
Promote ready cards → Up Next; demote not-ready cards out of Up Next → Backlog. Set a card's
column via GraphQL:
```bash
PROJ="PVT_kwHOD5-wHs4Bak8f"; FID="PVTSSF_lAHOD5-wHs4Bak8fzhVbjRw"; OPT="<option id>"
ITEM=$(gh api graphql -f query='{ repository(owner:"shanerconsulting",name:"pulse"){
  issue(number:N){ projectItems(first:10){ nodes{ id project{ id } } } } } }' \
  --jq ".data.repository.issue.projectItems.nodes[] | select(.project.id==\"$PROJ\") | .id")
gh api graphql -f query="mutation { updateProjectV2ItemFieldValue(input:{
  projectId:\"$PROJ\" itemId:\"$ITEM\" fieldId:\"$FID\"
  value:{ singleSelectOptionId:\"$OPT\" } }){ projectV2Item{ id } } }"
```

### 7. Report + fire
Hand back the final board: the fire-now set, the held set (with what unblocks each), the
not-ready set (with the staging each needs), and the wave order. Then `work` mode (one worktree
per card) burns down Up Next; you shepherd the serialized merge/review tail. Restore the prior
`gh` account when done.

## Considerations (the things that bite)

- **Concurrency is constant.** Re-snapshot before every prep and before every merge.
- **The human is the real ceiling — not compute.** Gate 1 taste cards and Gate 3 review can't be
  parallelized away; prep front-loads the David-work so the run goes unattended.
- **Don't over-prep.** Prep stops at "decided approach + acceptance + sequence."
- **Spikes are good wave fodder.** A go/no-go spike with concrete questions passes Gate 1 even
  when the underlying feature doesn't — its deliverable is findings, low stakes.
- **QA is real-app QA.** Each merged card still wants the menu-bar card exercised (`--qa`);
  budget the tail accordingly.
