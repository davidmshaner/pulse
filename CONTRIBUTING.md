# Contributing to Pulse

## Changelog (every PR)

Pulse keeps a human-curated [CHANGELOG.md](CHANGELOG.md) ([Keep a
Changelog](https://keepachangelog.com/en/1.1.0/) format). **Every PR that changes
behavior adds a bullet under `## [Unreleased]`** in the right category — Added /
Changed / Fixed / Removed — ending with `(#<issue>)`. Curate it for a human reader;
it is not a commit dump.

## The README "What's New" block

The top of [README.md](README.md) carries an auto-generated "What's New" block
(the last 30 days of releases) between `<!-- RECENT:START -->` and
`<!-- RECENT:END -->`. It is rendered from `CHANGELOG.md`, never hand-edited:

```bash
.venv/bin/python3 scripts/render_recent_changes.py          # rewrite the block
.venv/bin/python3 scripts/render_recent_changes.py --check  # exit 1 if stale (CI-friendly)
```

The script only ever touches text between the markers, and is idempotent.

## Cutting a release

Pulse installs from source (`git pull`), but external users still need a readable
"what changed". To release:

1. Decide the semver bump — MAJOR (breaking) / MINOR (feature) / PATCH (fix).
2. `echo <x.y.z> > VERSION`.
3. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [x.y.z] - YYYY-MM-DD` (today)
   and add a fresh empty `## [Unreleased]` above it.
4. Regenerate the README block: `.venv/bin/python3 scripts/render_recent_changes.py`.
5. Commit, open the PR, merge to `main`.
6. Tag and publish the GitHub Release from the new CHANGELOG section:
   ```bash
   git checkout main && git pull
   git tag v<x.y.z> && git pushx origin v<x.y.z>
   gh auth switch --user shanerconsulting
   gh release create v<x.y.z> --repo shanerconsulting/pulse --title "v<x.y.z>" \
     --notes "$(sed -n '/## \[<x.y.z>\]/,/## \[/p' CHANGELOG.md | sed '$d')"
   gh auth switch --user davidmshaner
   ```

The README block shows only the last 30 days; `CHANGELOG.md` is the full history.
