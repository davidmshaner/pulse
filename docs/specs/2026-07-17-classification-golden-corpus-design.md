# Classification golden corpus — regression QA for classifier heuristics

**Date:** 2026-07-17
**Status:** approved design, pre-implementation
**Motivating case:** #55 deliverable 2 (P3refined guardrail) — a heuristic change
that moves ~10 sessions, with no gate that would surface those movers for human
review before shipping.

## Problem

Every classifier heuristic change (code in `timecore/classify.py`, or an edit to
the user's `bucket-registry.yaml` / `disambiguation-rules.yaml`) can silently
re-bucket past sessions. Today the only "regression check" is regenerating output
and eyeballing it — nothing distinguishes *this change fixed a misclassification*
from *this change broke a correct one*, because there is no recorded ground
truth. The 2026-07-08 evidence-policy spike (`2026-07-08-evidence-policy-spike.md`)
built a one-off offline replay harness to measure exactly this for one change;
this design makes that capability permanent, with **hand-validated** expected
values instead of machine-frozen ones.

## Decisions (settled with David)

1. **Labeling model: seed + confirm movers.** All current confident
   classifications are seeded as `provisional` truth. A label becomes `confirmed`
   (hand-validated) only when David rules on it — which the tooling forces
   whenever a heuristic change makes an entry move. The hand-validated set grows
   exactly at the edge cases, with minimal labeling effort.
2. **Storage: gitignored repo file.** `golden-classifications.yaml` at the repo
   root, next to `bucket-registry.yaml` (same private-user-data pattern; added to
   `.gitignore`, path exposed as `config.GOLDEN`). It contains real absolute
   paths, so it must never be committed to this public repo.
3. **Entry shape: frozen evidence snapshot.** Each entry stores the extracted
   classifier *inputs* (not a pointer to the source JSONL), so entries survive
   Claude Code pruning old session logs and replay needs no re-parsing.
4. **Run surface: pytest gate + review CLI.** The gate rides the existing
   "pytest must be green" QA step; the interactive parts (seeding, ruling on
   movers) live in a small CLI.

## Design

### 1. Corpus file — `golden-classifications.yaml`

```yaml
entries:
  - id: 6f194f18-<uuid>.jsonl      # session file basename = stable id
    status: provisional             # or: confirmed
    expected_bucket: [venture-a, client-x]
    labeled_at: 2026-07-17          # present only once confirmed
    note: "skill-read-only session; the #55 edge case"   # optional
    evidence:                       # frozen classifier inputs, nothing else
      encoded: -Users-<user>-dev-...
      edit_paths: {"/abs/path": 3}
      read_paths: {"/abs/path": 7}
```

Privacy: evidence stores only paths and counts. `text_blob` / `first_msg` /
`bash_commands` never land in the file.

### 2. Replay engine — extract the shipping cascade

`prematch.py` currently inlines the session cascade (file_evidence →
project_dir_prefix → launch_dir_exact → needs_llm) in `main()`. Extract it into
a pure function in `timecore/classify.py`:

```
classify_session(sess, flat_buckets_sorted, excluded_paths, launch_dir_exact)
    -> (bucket_path | None, reason, evidence_scores)
```

`prematch.py` and the golden harness both call it, so the gate replays exactly
the shipping cascade and cannot drift from it. Replay runs against the **live**
registry + rules — registry edits are gated the same as code changes.

(Vendored-copy rule: `classify.py` exists as canonical + Pulse-vendored copies;
per the spike, changes apply to both, with a sync test. This extraction follows
that rule.)

### 3. pytest gate — `tests/test_golden_classifications.py`

Auto-**skips** (visibly, not silently passing) when `config.GOLDEN` is absent —
external users and CI have no corpus. Otherwise replays every entry and fails
on any of:

- **confirmed mismatch** — "regression against hand-validated truth", listing
  each mover as `id: old → new (reason)`.
- **provisional mismatch** — "N unreviewed movers — run
  `python3 -m pulse.golden review`", same table.
- **stale label** — `expected_bucket` no longer exists in the registry; distinct
  failure so a bucket rename can't masquerade as a pass or hide among movers.

Only the resulting **bucket** is asserted; `reason` and scores are shown in
failure output as diagnostics but are not part of the contract (a change that
reroutes a session through a different rule to the same bucket is not a mover).

All-match → ordinary green test. The sweep is pure in-memory (no JSONL, no
network, no LLM); well under a second for ~300 entries.

### 4. CLI — `python3 -m pulse.golden`

- **`seed`** — import current confident sessions from `.cache/prematch.json` as
  `provisional`. Append-only and idempotent by id; never modifies `confirmed`
  entries. Re-run any time to pick up new sessions.
- **`review`** — walk each current mismatch one at a time: launch dir, old vs
  new bucket + reason, top evidence paths/scores for each side. One-key verdict:
  - **new-right** → the change is a fix; entry re-baselines to the new bucket
    and becomes `confirmed`;
  - **old-right** → the change is a regression; entry pins to the old bucket as
    `confirmed` and the test stays red until the heuristic is fixed;
  - **skip** → leave for later (test stays red).
  With no mismatches pending, `review` can also walk unconfirmed entries for
  proactive spot-validation (e.g. a few easy anchors per bucket).
- **`status`** — confirmed/provisional counts + current mismatch table without
  failing anything.

### 5. Runtime lifecycle (trigger → verdict → resolution)

No daemon, no hook: the gate fires whenever `pytest` runs, which the pulse-dev
process already forces before any merge. A red gate is the verdict — the mover
table with David's name on the resolution. An agent working an issue cannot
pass its own QA gate without surfacing movers, and cannot "fix" the test
itself because the fix requires human verdicts via `review`. Every ruling
permanently grows the hand-validated set.

### 6. Fit with #55

Order of operations: build this harness → `seed` → confirm the spike's 10
movers plus a handful of easy per-bucket anchors → then implement P3refined.
Its branch turns the gate red on exactly those movers; `review` blesses them;
the hand-validated corpus is born from the real edge cases.

### 7. Testing the harness itself

Committable unit tests use a synthetic registry + synthetic entries (fake
paths, no real data): mismatch-fail paths (confirmed / provisional / stale),
skip-when-absent, seed idempotence and confirmed-preservation, and review
verdict application (new-right / old-right / skip).

## Out of scope

- Meeting classification (`classify_meeting`) — sessions only, for now. The
  entry shape doesn't preclude a future `meetings:` section.
- The LLM fallback (`needs_llm` path) — the corpus gates the deterministic
  cascade; sessions currently classified only by LLM aren't seeded.
- The minimum-confidence floor (#57) — orthogonal hardening; when built, it
  will be developed against this gate like any other heuristic change.
