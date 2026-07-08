# Design decisions: income-meter mode (#38) + nested groups (#31)

> Decided with David 2026-07-08. These two features share one underlying concern —
> evolving the `appetite.yaml` schema — so the calls were made together. Each issue
> carries its own acceptance criteria; this doc records the schema decisions the
> implementing agents inherit. (All dollar figures below are illustrative examples,
> not real engagement data — real config lives only in the user's gitignored
> `appetite.yaml`.)

## 1. Income-meter mode (#38): new explicit keys, NOT a rate-mode overload

An engagement in income-meter mode declares:

```yaml
engagements:
  ExampleClient:
    bill_rate: 200            # $/hr billed — presence of bill_rate selects income mode
    monthly_cap_value: 10000  # OPTIONAL — a $/month ceiling; omit for a pure running meter
```

- `bill_rate` alone → **pure meter**: the card shows running income, no bar, no ceiling.
- `bill_rate` + `monthly_cap_value` → **income cap**: progress toward the $ ceiling with
  `$X left` / `OVER $X`, mirroring how hour caps render today.
- **Rate-mode is untouched.** `monthly_value` + `target_rate` (dollars → derived hour cap)
  keeps its exact semantics for existing users. Validation MUST reject an engagement that
  mixes the two vocabularies (`bill_rate` alongside `monthly_value`/`target_rate`) with a
  loud preflight error rather than guessing.

## 2. Income meter window: calendar month-to-date

`$ billed = MTD actual hours × bill_rate`, resetting on the 1st — matching how hourly
clients are invoiced. NOT rolling-30d (never resets; drifts against a monthly cap). Weekly
$ figures are out of scope for v1; hours-based wtd/7d chips may remain as-is.

## 3. Nested groups (#31): recursive `members`

A group's `members` list may name **other groups** as well as engagements:

```yaml
groups:
  Billable:
    members: [ClientA, ClientB, ClientC]
    weekly_hours: 32
  Personal Software:
    members: [ProjectX, ProjectY]
  All Work:
    members: [Billable, Personal Software, Leftover]
    weekly_hours: 40
```

- No new field; the tree reads top-down in the file, matching the mental model.
- **Validator requirements (loud preflight failures, never silent miscounts):**
  unknown member name; membership cycles; an engagement counted via both a group and
  that group's ancestor (extend the existing `_group_overlap` ancestor/descendant
  guard, don't replace it).
- Bucket **splits** stay a registry concern: `children:` entries whose `source_path`
  is a subpath of the parent (already supported by `walk_registry` + rollup); the
  deliverable is the documented convention + a validator that a child's path is under
  its parent's.

## Sequencing

#38 and #31 both touch `snapshot.py` (caps/groups) + `frontend_common.py` — same
neighborhood, so they merge serially, one wave apart. Either may go first; the schema
validation each adds must compose (one preflight, two vocabularies).
