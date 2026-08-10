---
name: pulse-resolve
description: Categorize Pulse's uncategorized sessions and meetings, teach the registry so they stop recurring, and re-run the snapshot.
---

# Resolve Pulse's uncategorized work

Pulse could not confidently assign some sessions and meetings to a project. Your job
is to look at what they were, decide which project each belongs to, teach Pulse's
categorization files so the same items resolve automatically next time, and re-run.

Work in the `pulse` repo root — the parent of the `setup/` folder that contains this
file. The paste command names the absolute path (e.g. `In /path/to/pulse, read
setup/RESOLVE.md ...`); if your current working directory is elsewhere, `cd` into that
pulse repo first. Every path below is relative to it.

## 1. Read what's unresolved

Read `uncategorized.json` in the repo root. It has two lists:

- `sessions`: each has `project_dir` (where the Claude Code session ran), `session_file`
  (the transcript's JSONL basename — the key for a per-session override, step 3),
  `top_files` (the files it changed most — the real signal for *where the work landed*),
  `first_message` (what it was about), and `reason`.
- `meetings`: each has `title`, `attendees` (co-attendee emails), and `start`.

## 2. Find the categorization files

Pulse's category rules may be repo-local or pointed elsewhere by `config.yaml`. Resolve
the real paths first:

```bash
python3 -c "import config; print('registry:', config.REGISTRY); print('learnings:', config.LEARNINGS); print('rules:', config.RULES); print('overrides:', config.OVERRIDES)"
```

- **`registry`** (`bucket-registry.yaml`): maps a repo/folder root → a project category.
- **`learnings`** (`learnings.yaml`): maps a person's email → a project path. This is how
  a meeting gets attributed by who attended.
- **`rules`** (`disambiguation-rules.yaml`): tie-breakers for ambiguous folders.
- **`overrides`** (`session-overrides.yaml`): hand verdicts for *specific sessions* the
  classifier deliberately declines (see step 3). May not exist yet — create it on first use.

Read all three so you match their existing shape and category names exactly. Use a
category that already exists unless the work is genuinely a new project.

## 3. Resolve each session

For each session, use `top_files` and `project_dir` to decide the project (where the
work *landed*, not where the session started). Then in `bucket-registry.yaml`, add or
adjust the mapping so that repo root → the right category. If a folder legitimately maps
to more than one project depending on subpath, add a rule in `disambiguation-rules.yaml`
instead. Match the existing YAML structure exactly.

**If no folder mapping can express the verdict** — the classic shape is a session whose
only edit was its own auto-memory and whose only read was one reference file in a
*different* project's folder (the classifier declines these on purpose: the same shape
has opposite truths in different sessions) — write a per-session override instead of
bending the registry. In the `overrides` file (`session-overrides.yaml`), map the
session's JSONL basename to the bucket path:

```yaml
sessions:
  9f0ddf35-c59e-49c5-86a3-f0830fc8a88e.jsonl: [SC, ClientA]
```

The basename is the session's `session_file` field in `uncategorized.json`. Overrides fill only the
"couldn't decide" gap — a session with real file evidence keeps its evidence-based
category — and entries for sessions that have aged out of the window are harmless.
Teach the registry/learnings when a *mapping* is missing; write an override only for a
*one-off session* the cascade rightly refuses to generalize.

## 4. Resolve each meeting

For each meeting, use `title` + `attendees` to decide the project. In `learnings.yaml`,
add each genuinely-identifying co-attendee email under `patterns` mapping to the
project's path (e.g. `someone@clientco.com: [SC, ClientCo]`). Use the same path shape as
existing entries. Skip generic addresses (your own, large distribution lists) that don't
identify one project.

## 5. Re-run and confirm

```bash
python3 snapshot.py
```

Check the printed summary and confirm `uncategorized.json` shrank (sessions/meetings you
resolved should be gone). The menu-bar panel updates on its next refresh. Tell the user
what you categorized and where, in one short list.
