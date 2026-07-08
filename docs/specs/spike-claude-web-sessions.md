# Spike: Can claude.ai web-session activity power a Pulse scanner?

> Feasibility spike for #32. Findings only — no scanner built. Question: can
> **claude.ai web** activity (consumer Pro/Max subscription usage, not API-key
> traffic) be retrieved programmatically to become a Pulse source, the way
> `scan_sessions` reads Claude Code JSONL and `scan_cowork.scan` reads Cowork?
>
> Method: current Anthropic docs (July 2026) + read-only inspection of local
> artifacts on this Mac. No claude.ai login, no scraping of authenticated pages,
> no `ANTHROPIC_API_KEY` / billed calls. Example numbers below are rounded and
> carry no conversation content or client paths (privacy, #8).

## TL;DR — overall verdict

**No.** There is no supported, automatable, privacy-compatible source for
claude.ai **web-session activity** that Pulse can treat as a first-class source.
Every path is one of: wrong data (API-key traffic, not consumer chat), wrong
plan tier (Enterprise-only), not automatable (manual export), off-limits/fragile
(undocumented endpoints), or the wrong *shape* for Pulse (a coarse time signal
with **no project attribution** — and per-project billable minutes is Pulse's
entire unit of work).

The only signal that is automatable **and** privacy-light **and** low-fragility
is **browser-history dwell time** on `claude.ai` — a coarse "time on Claude web"
proxy, not session content, and with no way to bucket it to a project.

**Recommendation: do not build a web-session scanner.** If any web coverage is
wanted later, the single viable follow-up is the browser-history dwell proxy
behind an explicit opt-in, dumped into one catch-all `web/brainstorm` bucket
(see "Follow-up, if pursued"). Otherwise close the idea — this doc is the record
so it isn't re-investigated.

## Per-option verdicts

### 1. Anthropic public API (Messages API) — NO
The public API (`POST /v1/messages`) is **stateless** and serves only traffic you
originate with an API key; it stores and returns nothing about your claude.ai
chat history. A Pro/Max subscription grants claude.ai access, **not** API access
— they are separate systems on separate billing. There is no endpoint for
consumer web-session history, and building against it would also violate the
standing no-`ANTHROPIC_API_KEY` rule.
**Cost if pursued:** n/a — the data does not exist on this surface.

### 2. Admin API — Usage & Cost report — NO
`/v1/organizations/usage_report/messages` reports **organization API-key token
usage** grouped by model/workspace/key. It explicitly does **not** cover consumer
claude.ai (Pro/Max) usage. Wrong data source, and needs an Admin API key.
**Cost if pursued:** n/a — does not include the target data.

### 3. Enterprise Analytics API — NO (wrong plan tier)
This is the *only* Anthropic API that reports per-user engagement across chat +
Claude Code + Cowork surfaces — i.e. the thing #32 wants. But it requires a
Claude **Enterprise** plan; **Pro/Team are not supported**. Pulse's user is a
single-seat Pro/Max subscriber, so this is closed on plan tier alone. Worth
recording as the "if you were ever Enterprise" path, not a route for this user.
**Cost if pursued:** an Enterprise plan (org-level, not a code cost) — out of scope.

### 4. Account data export (Settings → Privacy → Export Data) — NO (not automatable, wrong shape)
Available on all plans; produces a downloadable archive of conversation data (format not documented in the support article). But it is a
**manual, retrospective** flow: click Export → wait → receive an **email link
that expires in 24h** → download. There is no API; automating it means scripting
an authenticated login + inbox polling + unzip — fragile and against the "no
scraping authenticated pages" constraint. It also delivers **full conversation
content** (max privacy exposure under #8, and the wrong shape — Pulse wants a
per-project time signal, not transcripts) and is not near-real-time. Even a
manual monthly export can't attribute time to a project.
**Cost if pursued:** high — headless-login automation + email retrieval + a
content-redaction layer, to extract a signal (timestamps) that's a thin slice of
a heavyweight payload. Not worth it.

### 5. OAuth / undocumented claude.ai endpoints — NO (off-limits + fragile)
The claude.ai web app is backed by internal, undocumented endpoints (the desktop
app's local cache exposes a `conversations_v*` store — see #6). Calling them
requires holding a live session cookie/OAuth token, is **ToS-fragile**, can break
without notice, and is squarely inside the task's "do not scrape authenticated
pages / do not log into claude.ai" prohibition. Assessed and rejected — do not
build against these.
**Cost if pursued:** ongoing maintenance against silent breakage + ToS risk. No.

### 6. Local Claude **desktop app** artifact (IndexedDB) — PARTIAL, but fragile + privacy-heavy + not the whole surface
The desktop app persists a local cache at
`~/Library/Application Support/Claude/IndexedDB/https_claude.ai_0.indexeddb.leveldb`.
Read-only inspection shows a `conversations_v*` object store keyed by
`uuid` / `timestamp` / `messages` (~3 MB here) — i.e. real conversation metadata
**and content**, on disk, readable without login. Tempting, but:
- **Only covers the desktop app.** claude.ai used in Safari/Chrome/Arc leaves
  nothing here. On this Mac the browser is the primary claude.ai surface, so the
  desktop cache would miss most of it.
- **Undocumented LevelDB schema** — no stable reader; the object-store layout can
  change on any desktop release (same fragility class as parsing another app's
  private cache).
- **Contains raw message content** → maximum #8 exposure; a scanner would have to
  read transcripts just to derive a timestamp.
- **It's a cache** — may be partial or evicted; not an authoritative log.
- **No project attribution** — like every option here, nothing maps a web chat to
  a Pulse project/bucket.
**Cost if pursued:** medium-high — a LevelDB reader + hard privacy guardrails +
per-release schema babysitting, for partial coverage. Not recommended.

### 7. Browser-history dwell time (the next-best signal) — VIABLE but coarse
Chrome's history DB (`~/Library/Application Support/Google/Chrome/Default/History`,
`visits` table) records a per-visit `visit_duration`, and it is **populated** for
claude.ai visits (~85% of rows here). Aggregating host = `claude.ai` gives a
usable **"time on Claude web"** proxy per day — on this Mac, hundreds of visits
over ~90 days with tens of minutes to a few hours on active days. Properties:
- **Automatable** and cheap: copy the SQLite file (it's locked while the browser
  runs), sum `visit_duration` for the `claude.ai` host in the window.
- **Privacy-light relative to every other option**: host + duration only — **no
  conversation content**. (Reading a user's full history is still sensitive → must
  be explicit opt-in, and the scanner must read only the `claude.ai` host, never
  store other URLs.)
- **Low fragility**: the Chromium history schema is stable and public.

Limitations that keep it a *proxy*, not a Pulse source:
- **Per-browser.** Chrome only here; Safari had a handful of visits, Arc/Brave
  none. Multi-browser users need multiple readers; the desktop app isn't covered
  at all. No single place captures "all claude.ai web time."
- **`visit_duration` is approximate** foreground/active time, reset on navigation
  — good for trend, not billing-grade.
- **No project/client attribution** — the core mismatch. Pulse exists to split
  billable minutes across projects; a claude.ai visit carries no project, so this
  can only ever feed one undifferentiated "web/brainstorm" bucket.
**Cost if pursued:** low-medium — see the follow-up sketch below.

## Follow-up, if pursued (NOT built in this spike)

Only the browser-history proxy (option 7) is worth a follow-up issue, and only if
David wants coarse web coverage despite no project attribution. Shape, mirroring
the existing cross-surface scanners:

- **New module** `src/pulse/scan_web.py` with `scan(window_start, window_end) ->
  list[dict]`, the same contract as `scan_cowork.scan` (returns session-shaped
  dicts; `compute_bucket_times` consumes `filepath` + `bucket_path`).
- It copies the Chrome history DB to a temp path (DB is locked in place), sums
  `visit_duration` for the `claude.ai` host within the window, and emits **one**
  synthetic session per day into a fixed `bucket_path` (e.g. `web/brainstorm`) —
  no project matching, because there is no project signal.
- **Hook** at `src/pulse/snapshot.py:552`, as a sibling of the `cowork_sessions =
  scan_cowork.scan(...)` line, so web minutes land in `per_path_minutes` and get
  the same cross-surface even-split dedupe.
- **Guardrails:** opt-in flag in `config.yaml` (default off); read only the
  `claude.ai` host, never persist other URLs; label the bucket clearly as an
  approximate proxy so it's never mistaken for billable, project-attributed time.

This stays a **coarse activity indicator**, explicitly not billable-minute parity
with Claude Code/Cowork sources. If that limitation isn't worth the surface area,
the correct move is to **close #32** and treat this doc as the durable "already
investigated, not viable" record.

## Sources
- [Anthropic Admin API — Usage & Cost](https://platform.claude.com/docs/en/manage-claude/usage-cost-api) — org API-key usage only; excludes consumer claude.ai.
- [Enterprise Analytics API coverage](https://www.finout.io/blog/anthropics-enterprise-analytics) — per-user chat/Code/Cowork usage, **Enterprise plan only** (Pro/Team unsupported).
- [Export your Claude data](https://support.claude.com/en/articles/9450526-how-can-i-export-my-claude-data) — manual Settings → Privacy export; email link, 24h expiry (file format not stated).
- [Claude Code issue #15542 — access Claude app chat history](https://github.com/anthropics/claude-code/issues/15542) — read-only access to claude.ai chat history is a requested, unimplemented feature.
- [Agent SDK issue #14 — retrieve historical messages](https://github.com/anthropics/claude-agent-sdk-typescript/issues/14) — no programmatic retrieval of prior session messages today.
- Local, read-only (this Mac): desktop app IndexedDB `conversations_v*` store; Chrome `History.visits.visit_duration` populated for the `claude.ai` host.
