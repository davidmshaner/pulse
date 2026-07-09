# Evidence-policy spike — file-evidence poisoning by global dirs (#55)

**Date:** 2026-07-08
**Issue:** shanerconsulting/pulse#55 (deliverable 1 of 2 — spike, no implementation)
**Question:** One internal bucket's registry `additional_paths` claims both
`~/.claude/projects` and `~/.claude/skills`. Every session writes auto-memory
under the former and reads user-level skills under the latter, so sessions
launched in *other* ventures' dirs gain file-evidence for that internal bucket
— and file-evidence outranks the launch-dir signal. Which exclusion policy
fixes this with the least collateral?

## Method

Deterministic offline replay of the prematch **session** pipeline over the full
corpus, using `.cache/sessions.json` (per-session `edit_paths`/`read_paths`
evidence) and the real registry — no network, no LLM, no re-parsing of JSONL.
The real `timecore/classify` primitives are imported unchanged, so the
**baseline replay reproduces `.cache/prematch.json` exactly: 0 / 307 interactive
sessions mismatched.** That validates the harness before any policy is varied.

Corpus: 1787 parsed sessions; **307 interactive** (only interactive sessions get
bucket-classified). Of those, **93 touch `~/.claude/skills`** and **59 touch
`~/.claude/projects`** in their evidence. Movers below are keyed by session file
(not the launch-dir "encoded" key, which many sessions share).

Policies compared (all vs baseline):

| Policy | Rule |
|---|---|
| **Baseline** | Current shipped behavior. `_is_self_memory` already drops each session's *own* `~/.claude/projects/<encoded>/memory/` from evidence. |
| **P1** | Exclude only the session's own memory dir. |
| **P2** | Exclude *all* of `~/.claude/projects` from evidence. |
| **P3** | P2 + exclude `~/.claude/skills` entirely. |
| **P4** | P2 + keep skill-read evidence but demote it: skill-only evidence can't outvote a launch-dir prefix match. |
| **P3refined** | P2 + reject only the *catch-all* global claims (a bucket whose `source_path` is exactly `~/.claude/skills` or `~/.claude/projects`); deeper/specific skill claims still count. (Added by the spike.) |

## Results

| Policy | Confident | needs_llm | Movers vs baseline | Hours moved |
|---|---|---|---|---|
| Baseline | 307 | 0 | — | — |
| **P1** | 307 | 0 | **0** | 0.0 |
| **P2** | 307 | 0 | **0** | 0.0 |
| **P3** | 307 | 0 | **10** | 17.0 |
| **P4** | 307 | 0 | **6** | 8.5 |
| **P3refined** | 307 | 0 | **10** | 17.0 |

No policy sends any session to `needs_llm` — every mover re-resolves to a bucket,
so there is **no added LLM cost**. Mover-set containment: **P4 ⊂ P3 = P3refined**
(P3refined moves exactly the same 10 sessions as P3, and P4 is a 6-session subset).

### Finding 1 — P1 is already shipped; P2 is a no-op; the whole live bug is the *skills* catch-all

`_is_self_memory` (the P1 rule) already ships in `classify.py`, and the baseline
cache was generated with it. So **baseline == P1**. Broadening to exclude *all*
of `~/.claude/projects` (P2) **moves zero sessions**: the only projects-dir
evidence any interactive session carries is its *own* memory dir, which P1
already drops. Cross-session memory poisoning does not occur in the corpus.

**Therefore the residual bug is entirely the `~/.claude/skills` catch-all claim.**
The decision reduces to how to treat that catch-all: exclude it (P3), down-weight
it (P4), or reject only the catch-all while keeping specific skill claims
(P3refined).

### Finding 2 — P4 under-corrects; it only rescues *pure* skill-only sessions

P4 demotes skill evidence *only when it is the sole bucket-matching signal*. When
a session's skill-reads coexist with a little real venture evidence but outweigh
it, P4 still lets the skills decide. Measured consequence: P4 fixes the 6 clean
"skill-read is the entire signal" sessions but **misses the dominant real cases**
— e.g. both venture-A `/bootup` sessions, where a user-level skill read outweighs
(but does not wholly replace) the session's real venture-A evidence. P3/P3refined
strip the catch-all and let that real evidence surface, routing them correctly.

### Finding 3 — P3refined == P3 in corrections, with none of P3's collateral

Four other buckets legitimately claim *specific* skill subfolders (two
pipeline skills, two content-prep skills). Raw
P3 excludes `~/.claude/skills` wholesale and would silently void those claims.
P3refined rejects only the two *catch-all* claims and keeps the specific ones —
and it **produces the identical 10-mover result** on this corpus (no session
relied on a specific-skill claim for its file evidence; those sessions were
already launch-dir-classified). So P3refined is a strict improvement over P3:
same corrections today, zero latent regression to the specific claims.

### Finding 4 — the "genuine skill-infra" criterion is protected structurally

Acceptance criterion: sessions that genuinely work on skill/memory infrastructure
(launched *in* those trees, editing them substantively) must still land on the
internal bucket. **No interactive session in the corpus was launched inside
`~/.claude/skills` or `~/.claude/projects`.** And structurally it doesn't matter:
every policy filters only *file evidence* — none touch `encoded_matches` /
`classify_session_by_project_dir`, so a session whose launch dir is a global tree
still resolves to the internal bucket via the launch-dir prefix. The protective
path is preserved by construction under P2/P3/P4/P3refined.

## Spot-check of the movers (verdicts by hand)

Buckets are generic labels: **internal** = the poison bucket; **consulting
parent** = its top-level parent; **venture A**, **venture B** = other ventures;
**$-billed client** = a client under the consulting parent. "Truth" is my read of
the session's first message + evidence.

| # | min | Baseline → mover result | Policy that moves it | Sole global evidence | Truth | Verdict |
|---|---|---|---|---|---|---|
| 1 | 33.0 | internal → **venture A** (launch-dir) | P4 & P3ref | one user-level skill read | venture A | ✅ correct |
| 2 | 1.0 | internal → **venture A** (launch-dir) | P4 & P3ref | one deploy-week context read | venture A (launched there) | ✅ correct |
| 3 | 41.9 | internal → **consulting parent** (launch-dir) | P4 & P3ref | one `/voice` skill read | $-billed client (under consulting) | ✅ correct tree |
| 4 | 190.5 | internal → **consulting parent** (launch-dir) | P4 & P3ref | one infra-script read | consulting infra | ✅ same tree |
| 5 | 21.8 | internal → **consulting parent** (launch-dir) | P4 & P3ref | edits a skill file (`/voice`) | consulting infra | ✅ same tree |
| 6 | 223.6 | internal → **consulting parent** (launch-dir) | P4 & P3ref | one deploy-week context read | app-dev talk | ✅ off internal (coarse) |
| 7 | 29.6 | internal → **venture A** (file-ev) | P3ref only | `/bootup` skill + venture-A memory | venture A | ✅ correct — **P4 misses** |
| 8 | 27.2 | internal → **venture A** (file-ev) | P3ref only | `/bootup` skill | venture A | ✅ correct — **P4 misses** |
| 9 | 15.8 | internal → **venture B** (file-ev) | P3ref only | one deploy-week context read | venture B (launched there) | ✅ correct — **P4 misses** |
| 10 | 436.4 | internal → **venture B** (file-ev) | P3ref only | a quarterly-update skill (many reads) | **venture A** | ⚠️ wrong venture |

Mover 10 (7.3h) is the one blemish: once skill evidence is stripped, its entire
attribution flips to venture B on a **single 0.2-weight incidental file read**.
But note it is **mislabeled under every policy** — baseline and P4 leave it on
*internal* (also wrong; truth is venture A). P3refined doesn't make a
previously-correct session wrong; it relocates an already-wrong 7.3h session
laterally. Its root cause is a *separate* latent weakness: **the matcher will
confidently classify on a single low-weight read with no minimum-confidence
floor.** That is out of scope for #55 and is called out as a follow-up below.

**Scorecard (venture-tree correctness of movers):**
- **P3refined:** 9 / 10 land in the correct venture-tree; 1 lateral wrong→wrong (mover 10). 0 previously-correct sessions made wrong.
- **P4:** 6 / 6 correct, but leaves 4 known-poisoned sessions (movers 7–10, incl. the 7.3h one) still mislabeled on *internal*.

## deploy-week finding (does it share this code path?)

**Two copies of `classify.py` exist, and they have already drifted:**

- **Canonical:** the `timecore/classify.py` in a shared `code-blocks` skills tree *outside* this repo. deploy-week's `prematch.py` imports it cross-tree via `sys.path`.
- **Vendored snapshot:** `src/pulse/timecore/classify.py` inside this repo. The public Pulse repo ships its own copy.

Both already contain `_is_self_memory` (P1), but only the **Pulse** copy has
`classify_session_by_launch_dir_exact` (added in Pulse #40/#41); the canonical
copy does not. So the snapshot is *already* ahead of canonical — proof that a
code change made in Pulse does **not** reach deploy-week automatically.

Two more coupling facts:

1. **Shared registry.** `config.REGISTRY` resolves to
   `deploy-week/context/bucket-registry.yaml` — the *same* file both consumers
   read. A registry edit changes both at once.
2. **deploy-week sets `ROOT_REDIRECT` at runtime** (`{("consulting parent",):
   ["consulting parent","internal"]}`); Pulse leaves it empty. So a session that
   lands on the bare consulting-parent bucket is redirected to *internal* in
   deploy-week but not in Pulse. Consequence for this spike: movers 3–6 (which
   go to the consulting parent) would be **re-absorbed into internal** inside
   deploy-week, so there they are no-ops — deploy-week's net effect under
   P3refined is only the cross-venture corrections (movers 1, 2, 7, 8, 9 correct;
   10 wrong). This is arguably *cleaner* in deploy-week: the coarse "→ parent"
   moves vanish and only true cross-venture leakage is corrected.

**Desync implication:** a code-only guardrail added to Pulse's vendored
`classify.py` will silently *not* fix deploy-week (the real weekly report) unless
the same edit is applied to the canonical copy too. The **registry-convention fix
lives in the shared registry and fixes both consumers identically, independent of
the code drift** — which is the strongest reason to make it the primary lever.

## Recommendation

**Winning policy: P3refined — reject the catch-all global claims from file
evidence (keep specific skill claims) — paired with the registry convention as
the primary lever.**

Why P3refined over the literal-criteria P4: the numbers. P4 matches the issue's
"weight so skills can't outvote launch-dir" wording, but on measurement it
under-corrects — it only rescues pure skill-only sessions and leaves the dominant
real cases (both `/bootup` sessions, a launched-in-venture-B session, and the
7.3h session) still mislabeled on *internal*. P3refined corrects 3 more sessions
to their right venture and makes **zero** previously-correct sessions wrong; its
one debit is a session that is wrong under every policy anyway. Over raw P3 it is
strictly safer (keeps the four legitimate specific-skill claims) at identical
correction power.

**Two-layer fix for deliverable 2:**

1. **Registry convention (primary, shared-data):** an `additional_paths` entry
   must never be a directory that *every* session touches as a side effect —
   specifically `~/.claude/projects` and the bare `~/.claude/skills`. Remove
   those two catch-all claims from the internal bucket. Keep the *specific*
   skill-subfolder claims. Because the registry is shared, this fixes Pulse and
   deploy-week at once. Add a **validator warning** when any `additional_path`
   equals a known global dir, so the mistake can't silently return.
2. **Code guardrail (defense-in-depth):** implement the P3refined rule in
   `classify.py` — in the matcher, a match whose bucket `source_path` is *exactly*
   a catch-all global dir is not evidence (deeper claims still count). This keeps
   classification correct even if a future registry re-introduces a catch-all
   claim. **Apply it to both `classify.py` copies** (canonical + Pulse vendored)
   or the consumers desync; add a test asserting the two files stay in sync.

**Out of scope (follow-up issue):** the minimum-confidence gap surfaced by mover
10 — the matcher will confidently classify a multi-hour session on a single
0.2-weight incidental read. A small floor (e.g. require the winning file-evidence
score to clear a threshold, else fall to launch-dir/`needs_llm`) would harden
attribution generally and neutralize the one blemish above. It is orthogonal to
the global-path poisoning this issue targets.

## Reproduction

The offline harness (imports the real `timecore/classify`, replays all six
policies, validates against `.cache/prematch.json`, and prints the mover tables)
is deterministic over `.cache/sessions.json` + the registry. It reads real user
data (client names, absolute paths) so it is intentionally **not committed** to
this public repo; it lives in the spike's scratch working area. Anyone can
regenerate the numbers by pointing the same replay at `config.REGISTRY`.
