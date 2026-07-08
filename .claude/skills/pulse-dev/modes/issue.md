# `/pulse-dev --issue` — Intake

> Mode of `/pulse-dev` (see `../SKILL.md`). Turn a raw ask into a fully-contextualized GitHub issue
> on `shanerconsulting/pulse` + the Pulse board. The issue body IS the downstream agent's entire
> context, so manufacture enough that a cold agent runs to a PR without asking.

## Flow

### 1. Capture
Take what's given. Ask at most 1-2 clarifying questions, ONLY if intent or acceptance is genuinely
unclear. Don't interrogate.

### 2. Enrich (this is the value — do the legwork)
Against the Pulse repo:
- **Relevant code:** grep/glob `src/pulse/` (and `tests/`) for the files + symbols the ask touches.
  Cite as `path — symbol/function name (what lives here)`; **anchor by SYMBOL, not raw line
  number** — the repo ships often and every line number goes stale before pickup (a line number
  is fine only as a secondary hint next to the symbol). Never invent a path; say "none found". (Orientation:
  `app.py` is the rumps menu-bar entry; `scan_sessions.py` / `scan_cowork.py` read Claude Code
  JSONL; `live_bucket.py` / `snapshot.py` do the time accounting; `fetch_meetings.py` pulls
  calendar; `config.py` owns `PKG_DIR`/`DATA_DIR`; `frontend_common.py` / `app_win.py` the UI.)
- **Spec / plan:** look under `docs/specs/` and `docs/plans/` (and `docs/superpowers/`) for a related
  design; name it.
- **Gotchas:** scan `process/conventions.md` "Known issues" and cite any the work risks tripping
  (the rumps disabled-gray trap, the Python.app process-kill caveat, the borderless-overlay quirk).
- **Privacy scrub (the repo is PUBLIC — issues are public pages):** genericize client data before
  drafting. No real client names, billing rates, monthly values, caps, or per-client hours in the
  issue body — use `ExampleClient` / round illustrative figures and phrases like "an hourly-billed
  engagement". Real config stays in the user's gitignored `appetite.yaml`/registry; an issue may
  point at it ("the hourly engagement's block") without quoting it. External users' and testers'
  names: refer to them by role ("an external Pulse user") unless they're already public
  contributors. (Learned 2026-07-08: five public issue/PR bodies had to be scrubbed and their
  edit-history revisions manually deleted.)

### 3. Dedup check (HARD GATE — before drafting)
Never create without checking for an existing match. List open AND recently-closed issues, judge by
intent (not title-string):
```bash
gh auth switch --user shanerconsulting >/dev/null 2>&1
gh issue list --repo shanerconsulting/pulse --state open  --limit 60 \
  --json number,title,labels --jq '.[] | "#\(.number) [\(.labels|map(.name)|join(","))] \(.title)"'
gh issue list --repo shanerconsulting/pulse --state closed --limit 25 \
  --json number,title --jq '.[] | "#\(.number) \(.title)"'
gh auth switch --user <prior-account> >/dev/null 2>&1   # restore
```
- Overlap with an OPEN issue → recommend a comment (`gh issue comment`), not a dup.
- Overlap with a CLOSED issue → surface it (regression/follow-up); David decides.
- Distinct → draft. Batch: run the check once, present keep/drop/comment split.

### 4. Classify
Pick exactly ONE type label:

| Signal | Label |
|---|---|
| Something is broken / wrong behavior | `bug` |
| New capability / net-new feature | `feature` |
| Improvement to existing behavior | `enhancement` |
| Hygiene, docs, deps, no user-facing change | `chore` |
| Refactor / debt paydown / known-shortcut cleanup | `tech-debt` |

The issue body names the area (menu-bar card, time accounting, session scan, cowork scan, calendar,
config, install) — no component labels. Column is always **Backlog** (David triages Backlog → Up
Next; the board carries the 6 stages Backlog → Up Next → In Progress → In Review → QA → Done).

### 5. Draft + CONFIRM (hard gate)
Assemble a fields JSON (schema below) and run the script `--dry-run`; show the rendered body +
planned label + board action + the dedup verdict. NOTHING is written to GitHub until David approves.

### 6. Create + place
On approval, run without `--dry-run`. The script ensures the shanerconsulting account is active,
creates the issue with explicit `--repo`, places it on the board in Backlog, and restores the prior
account. Report the issue URL. (Board placement needs the board to exist — `--bootstrap` first, and
`board_number` set in `context/board-config.json`.)

## Runner detection
Detect via `git config user.email`: David → `origin: "david"`; an orchestrating agent → `origin:
"agent"` (note "agent-filed, David to triage" in Context).

## Fields JSON schema
```json
{
  "title": "<readable title>",
  "labels": ["bug"],
  "origin": "david",
  "body": {
    "intent": "<one sentence: outcome>",
    "context": "<why now; repro steps / quote>",
    "relevant_code": ["src/pulse/snapshot.py:120 — what lives here"],
    "acceptance": ["observable outcome 1", "outcome 2"],
    "approach": "<entry points; which superpowers skill to reach for>",
    "watchouts": {"gotcha": "...", "spec": "path ...", "area": "time accounting"}
  }
}
```
Leave any enriched field empty and the script renders an explicit "none" marker.

## Invocation
```bash
# preview first (the confirm gate)
python3 .claude/skills/pulse-dev/scripts/pulse_issue.py --fields /tmp/pulse-issue.json --dry-run
# create after approval
python3 .claude/skills/pulse-dev/scripts/pulse_issue.py --fields /tmp/pulse-issue.json
```
Board placement needs the `project` scope on the shanerconsulting token; if the script stops with
that message: `gh auth refresh -s project --user shanerconsulting` (one-time). The board itself is
provisioned by `bootstrap.md`.

## Scope
Pure intake. No PRs, no worktrees, no promotion past Backlog, no label/board creation. The
compounding-feedback loop (in `work.md`) edits THIS doc's Enrich step when a cold pickup reveals
missing context.
