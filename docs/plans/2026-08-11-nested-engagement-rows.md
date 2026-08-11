# Nested engagement rows (#66)

## Problem
Since nested groups (#31) the card renders the GROUP tree with depth-indented rows, but
ENGAGEMENTS still render as one flat list appended after all groups. An engagement that is a
member of a group (e.g. `ClientA` under `Billable`) shows at top level below the whole tree,
while a sub-group member nests correctly — the hierarchy reads wrong.

## Design
Render order becomes one interleaved tree walk: each group row, then its sub-group subtrees,
then its own direct member engagements indented one level deeper (`depth = parent + 1`).
Engagements that belong to no group render at the end, un-indented (today's behavior for them).
Groups-before-engagements within a section: the group-row sequence is byte-identical to today's;
member engagements slot in at the end of their parent's section (file-browser convention:
folders first, then files).

### Data (snapshot.py)
Each group block in `state.json` gains `direct_engagements`: the group's *direct* member names
that are engagements, in config order. A wildcard (`members: "*"`) group claims nothing — `*` is
a roll-up statement, not a hierarchy claim, and honoring it would steal every engagement from
the groups that explicitly list them (including the `Billable` group synthesized for legacy
`total_budget:` configs, which must keep the flat pre-#66 layout). Distinct from the existing
`members` key, which is the *resolved leaf* list used for cap math. An old state.json without
the key renders exactly as before (flat engagement tail) — graceful downgrade.

### Shared walk (frontend_common.iter_rows)
One walk used by BOTH frontends yields `(kind, name, block, depth)` in render order via a stack
walk: emit group; hold its direct engagements; flush them when the walk leaves that group's
subtree; unclaimed engagements last at depth 0. An engagement listed by two groups renders once,
under its DEEPEST listing parent (most-specific wins; ties keep the first in tree order) — so a
parent that also lists a sub-group's engagement doesn't steal it. Legacy `total` fallback lives
here too.

### HTML panel (render_state.py + template.html)
`build_view_model` emits a single ordered `rows` list (replacing the `groups` + `engagements`
keys); `template.html` renders `VM.rows` in one loop and filters `is_group` rows for the
overlap warning. The existing engagement sort (capped-over first, then capped, then track-only,
alpha within) applies per sibling set — contiguous same-depth engagement runs from the walk —
instead of globally. Flat/legacy configs produce the same row order and no `depth` keys, so the
rendered DOM stays byte-identical (the #31 guarantee, judged at the rendered-output layer).

### Text fallback (frontend_common.menu_lines)
Same walk; engagement line painters extracted to helpers that take an indent prefix
(`"  " * depth`), zero-width at depth 0 so flat configs render today's exact lines.

## Out of scope
Mixed group/engagement sibling sorting (groups keep definition order); collapsing; Windows
tkinter styling beyond what `menu_lines` already feeds it.

## Tests
- snapshot: `direct_engagements` = direct engagement members only (sub-groups excluded);
  wildcard → all engagements.
- render_state: interleaved `rows` order + engagement depth; per-sibling sort; unclaimed
  engagements last at depth 0; flat/legacy state → old order, no depth keys anywhere.
- frontend_common: `iter_rows` walk order; `menu_lines` indents member engagement lines;
  flat state lines unchanged.
