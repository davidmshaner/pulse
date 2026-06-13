# `/pulse-dev` (default) — Work an Issue

> Mode of `/pulse-dev` (see `../SKILL.md`). `--issue` puts issues on the board; this takes them off
> and ships them. The executor: isolate → build → gate → PR → review → merge → Done. Engineering
> craft is delegated to superpowers; this doc is the Pulse-specific routing.

## Two ways in
- **No target** (`/pulse-dev`) → pick an issue (the Pick gate below).
- **A target** (`/pulse-dev #9`, or a description) → resolve to one issue, jump to Isolate.

## Autonomy: confirm the issue, then run
The one routine stop is at **issue selection**: show David the proposed issue + a one-line plan and
wait. Once he confirms, run to an open PR without pausing at each step. **Always stop before merge.**
(A directly-given target is the confirm.) A plan deviation mid-flight (skip/defer/reorder a planned
task) is a stop-and-ask, never a silent judgment call.

## 1. Pick (only when no target was given) — gate
List the board's **In Progress** column (David promotes Backlog → In Progress, so In Progress is the
ready queue), propose ONE issue, read its body:
```bash
gh auth switch --user shanerconsulting >/dev/null 2>&1
gh issue list --repo shanerconsulting/pulse --state open --json number,title,labels \
  --jq '.[] | "#\(.number) [\(.labels|map(.name)|join(","))] \(.title)"'
gh issue view <n> --repo shanerconsulting/pulse --json number,title,labels,body
gh auth switch --user <prior-account> >/dev/null 2>&1
```
Priority: a `bug` outranks `enhancement`/`feature`; a ripe issue (spec/repro in the body, no open
question) outranks one needing design. State WHY it's the pick and that it's your judgment. **No
eligible issue?** Say so; offer to pull from Backlog or file one via `--issue`. Don't invent work.
Present the issue + one-line plan, **wait for the confirm.**

## 2. Isolate — a worktree per issue
```bash
git worktree add .worktrees/issue-<n> -b issue-<n>
```
Pulse keeps worktrees under the gitignored `.worktrees/`. Parallel agents each take a distinct issue;
no shared `main`. Move the board item to **In Progress** if it isn't already (usually David did at
triage; with the bootstrap automations, opening a PR that `Closes #<n>` also advances it).

## 3. Build — the superpowers stack, sized to the work
| Work shape | superpowers skill |
|---|---|
| Design is open / ambiguous | `brainstorming` → `writing-plans` |
| Multi-step feature with a spec | `writing-plans` → `executing-plans` (or `subagent-driven-development` to fan out) |
| New / changed behavior | `test-driven-development` |
| Small bug fix | skip to a failing test + fix |

Plans/specs go to `docs/plans/` and `docs/specs/`. Pulse reads Claude Code session JSONL + calendar;
it makes **no metered API calls**, so there is no paid-API cost gate.

## 4. Gate (QA) — tests green AND the real app exercised
**`pytest` must be green** (run from the repo root: `python3 -m pytest -q`). Then, because Pulse has
a **far QA boundary**, run the actual app and read the menu-bar card to verify the change on the real
user path. Full procedure: **`qa.md`**. The `pytest` gate + the app read together are the closing
gate of this step.

## 5. PR → review → merge
Open a PR against `main`, `Closes #<n>`. **Review before merge** — `/code-review`, or dispatch a
fresh diff-only review subagent (agent-authored work should not merge unreviewed). Fix the real
findings. On merge: board item → **Done** (the bootstrap automation does this on merge; verify it
landed), then `git worktree remove .worktrees/issue-<n>`. Conventions (branch+PR+worktree, the
shanerconsulting account rule, run/reinstall) live in `../process/conventions.md`.

## 6. Compounding feedback
Before closing, ask: did I have to discover anything the issue should have carried (a repro, a file
path, an area, a gotcha)? If yes, make a narrow edit to `issue.md` (its Enrich step) so the next
issue of that shape carries it cold. If nothing was missing, say so; don't manufacture a change.

## Concurrency (thin)
Worktrees isolate your files, and parallel agents take distinct issues, so collisions are rare.
Still: before merging, `git fetch origin main && git diff --stat origin/main..HEAD` — the diff should
be only your files; if not, rebase onto fresh `origin/main` first. If another agent is live, read it
before merging (`--tail`, see `tail.md`). There is no shared deploy/prod target to serialize —
`main` is the only shared resource.

## Scope
Execution only — isolate through merge, plus the QA gate and the feedback loop. It does not file
issues (`--issue`) or provision the board (`--bootstrap`). There is no release/deploy step — a merge
to `main` (and a relaunch to pick up changes) is the end.
