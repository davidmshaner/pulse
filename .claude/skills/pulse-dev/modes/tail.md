# `/pulse-dev --tail` — Coordinate with a Parallel Agent

> Mode of `/pulse-dev` (see `../SKILL.md`). Thin wrapper. Pulse runs parallel agents, each on a
> distinct issue in its own `.worktrees/` worktree, so collisions are rare — but `main` is shared,
> so read before you merge. The reading is done by the general `tail-agent` tool (global infra used
> across projects), not buried here.

## When to tail (the Pulse trigger)
- Before merging, if `git fetch origin main && git diff --stat origin/main..HEAD` shows files you
  never touched — another agent pushed; read it before you rebase/merge.
- When David says "tail the other agent" / "what's the other Pulse agent doing".
- Lower-stakes than GI: there is **no shared deploy or prod target** to serialize. The only shared
  resource is `main`, and worktree-per-issue keeps file collisions rare.

## The tool
```bash
S=~/.claude/skills/tail-agent/tail_agent.py
python3 $S list                    # candidates newest-first; "LIVE" = written <90s ago (mtime, not filename)
python3 $S peek <session-prefix>   # last ~40 events
python3 $S follow <prefix>         # live tail (background, then check output)
python3 $S --dir .worktrees/issue-<n> list   # add a specific worktree's project dir
```
The script auto-excludes your own session and scans every project dir whose encoded path starts with
your cwd (catches the `.worktrees/issue-<n>` worktrees automatically).

## Procedure
1. `list` — the transcript with mtime updating now (`LIVE`) is the other agent (mtime, never
   filename — UUIDs are random).
2. `peek` it — which issue, which files, is it about to push/merge.
3. Corroborate with git: `git log --oneline --all -15`, `git show --stat <commit>`.
4. Coordinate, don't race: if it's mid-merge, wait or rebase after it lands. Confirm your pre-merge
   diff is only your files.

## Scope
Read-only reconnaissance. Never kills the other agent or decides merge order — it gives you the
facts. Full tool reference: `~/.claude/skills/tail-agent/SKILL.md`.
