---
name: pulse-resolve
description: Categorize Pulse's uncategorized sessions and meetings, teach the registry so they stop recurring, and re-run the snapshot.
---

# Resolve Pulse's uncategorized work

Pulse could not confidently assign some sessions and meetings to a project. Your job
is to look at what they were, decide which project each belongs to, teach Pulse's
categorization files so the same items resolve automatically next time, and re-run.

Work in the `pulse` repo root.

## 1. Read what's unresolved

Read `uncategorized.json` in the repo root. It has two lists:

- `sessions`: each has `project_dir` (where the Claude Code session ran), `top_files`
  (the files it changed most — the real signal for *where the work landed*),
  `first_message` (what it was about), and `reason`.
- `meetings`: each has `title`, `attendees` (co-attendee emails), and `start`.

## 2. Find the categorization files

Pulse's category rules may be repo-local or pointed elsewhere by `config.yaml`. Resolve
the real paths first:

```bash
python3 -c "import config; print('registry:', config.REGISTRY); print('learnings:', config.LEARNINGS); print('rules:', config.RULES)"
```

- **`registry`** (`bucket-registry.yaml`): maps a repo/folder root → a project category.
- **`learnings`** (`learnings.yaml`): maps a person's email → a project path. This is how
  a meeting gets attributed by who attended.
- **`rules`** (`disambiguation-rules.yaml`): tie-breakers for ambiguous folders.

Read all three so you match their existing shape and category names exactly. Use a
category that already exists unless the work is genuinely a new project.

## 3. Resolve each session

For each session, use `top_files` and `project_dir` to decide the project (where the
work *landed*, not where the session started). Then in `bucket-registry.yaml`, add or
adjust the mapping so that repo root → the right category. If a folder legitimately maps
to more than one project depending on subpath, add a rule in `disambiguation-rules.yaml`
instead. Match the existing YAML structure exactly.

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
