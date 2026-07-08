"""updatecheck.py — is this Pulse clone behind shanerconsulting/pulse main? (issue #25)

Pulse ships as a hand-updated git clone (`git pull && bash install-mac.sh`), so when a
fix lands on main an installed user has no in-app signal that they're stale. This module
decides that one boolean — "behind the public remote's default branch" — by comparing the
local HEAD sha to the remote main sha from the *public* GitHub API. snapshot.py folds the
result into state.json; the card renders a banner from it.

Contract: the whole module is FAIL-SILENT. Offline, GitHub-unreachable, rate-limited,
a 404, a shallow/detached clone, malformed JSON, an unreadable `.git` — every one resolves
to "no banner" (behind=False), never an exception into the menu-bar run loop. It runs on
the snapshot tick (already off the main thread, in the killable pipeline subprocess), and
is throttled so a real GitHub request happens at most once per `THROTTLE_SECONDS`.

Privacy (issue #8): only git/version metadata crosses the network or is logged — the
40-char commit shas and the public repo URL. No session content, no file paths, no client
names are read, sent, or persisted here.

stdlib-only (urllib) so snapshot.py imports it with no new dependency, and every path is
unit-testable with an injected opener + fake `.git` trees (no live GitHub call in tests).
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.error import URLError

REMOTE_URL = "https://api.github.com/repos/shanerconsulting/pulse/commits/main"
# A real network request at most this often. The snapshot loop runs every ~600s, so
# without this it would poll GitHub 6x/hour; 6h keeps us far under the 60/hour
# unauthenticated limit while local-HEAD recompute (cheap) still runs every snapshot so
# the banner clears the moment the user actually updates.
THROTTLE_SECONDS = 6 * 3600
_TIMEOUT = 6.0
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


# --- local HEAD ------------------------------------------------------------

def _git_dir(repo_dir: Path) -> Path | None:
    """The gitdir for `repo_dir`. `.git` is a directory in a normal clone, or a file
    (`gitdir: <path>`) in a submodule/worktree; resolve both. None if neither."""
    dotgit = Path(repo_dir) / ".git"
    if dotgit.is_dir():
        return dotgit
    if dotgit.is_file():
        txt = dotgit.read_text().strip()
        if txt.startswith("gitdir:"):
            p = Path(txt[len("gitdir:"):].strip())
            return p if p.is_absolute() else (Path(repo_dir) / p).resolve()
    return None


def _common_dir(git_dir: Path) -> Path | None:
    """A worktree gitdir keeps shared refs in a sibling common dir named by `commondir`."""
    cd = git_dir / "commondir"
    if cd.is_file():
        p = Path(cd.read_text().strip())
        return p if p.is_absolute() else (git_dir / p).resolve()
    return None


def _resolve_ref(git_dir: Path, ref: str) -> str | None:
    bases = [git_dir]
    common = _common_dir(git_dir)
    if common is not None and common != git_dir:
        bases.append(common)
    # loose ref file first
    for base in bases:
        loose = base / ref
        if loose.is_file():
            val = loose.read_text().strip()
            if _SHA_RE.match(val):
                return val
    # then packed-refs
    for base in bases:
        packed = base / "packed-refs"
        if packed.is_file():
            for line in packed.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "^")):
                    continue
                sha, _, name = line.partition(" ")
                if name == ref and _SHA_RE.match(sha):
                    return sha
    return None


def read_local_head(repo_dir: Path) -> str | None:
    """The 40-char sha `repo_dir` currently has checked out, or None if unreadable.

    Reads the git plumbing directly (no `git` binary, so it works under the LaunchAgent's
    minimal PATH): HEAD is either a detached sha or `ref: <refname>` resolved via loose
    refs / packed-refs. Any surprise (missing, garbage, permissions) returns None."""
    try:
        git_dir = _git_dir(repo_dir)
        if git_dir is None:
            return None
        head = (git_dir / "HEAD").read_text().strip()
        if _SHA_RE.match(head):
            return head
        if head.startswith("ref:"):
            return _resolve_ref(git_dir, head[len("ref:"):].strip())
        return None
    except OSError:
        return None


def read_head_branch(repo_dir: Path) -> str | None:
    """The branch name HEAD symrefs to (e.g. 'main'), or None if detached/unreadable.

    Used to keep the banner honest on a dev checkout: a feature branch (or detached
    HEAD) differs from remote main for reasons that are not \"you are behind\", so the
    banner only ever fires when HEAD is actually on main."""
    try:
        git_dir = _git_dir(repo_dir)
        if git_dir is None:
            return None
        head = (git_dir / "HEAD").read_text().strip()
        prefix = "ref: refs/heads/"
        if head.startswith(prefix):
            return head[len(prefix):].strip() or None
        return None
    except OSError:
        return None


# --- remote HEAD -----------------------------------------------------------

def _default_opener(url: str, timeout: float):
    req = urllib.request.Request(url, headers={
        "User-Agent": "pulse-update-check",
        "Accept": "application/vnd.github+json",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_remote_head(url: str = REMOTE_URL, opener=_default_opener,
                      timeout: float = _TIMEOUT) -> str | None:
    """The sha of shanerconsulting/pulse main from the public GitHub API, or None.

    `opener(url, timeout) -> response` is injectable so tests never touch the network.
    Every failure mode (offline, timeout, HTTP error, non-JSON body, missing/short sha)
    returns None — the caller treats None as 'couldn't determine remote'."""
    try:
        resp = opener(url, timeout=timeout)
        try:
            data = resp.read()
        finally:
            close = getattr(resp, "close", None)
            if callable(close):
                close()
        sha = json.loads(data).get("sha")
        return sha if isinstance(sha, str) and _SHA_RE.match(sha) else None
    except (URLError, OSError, ValueError, TypeError):
        # URLError covers HTTPError (404/403/rate-limit) + offline; OSError covers
        # socket timeout; ValueError covers bad JSON; TypeError covers a weird body.
        return None


# --- orchestration ---------------------------------------------------------

def _elapsed(prior: dict | None, now: datetime) -> float | None:
    if not prior or not prior.get("checked_at"):
        return None
    try:
        then = datetime.fromisoformat(prior["checked_at"])
    except (TypeError, ValueError):
        return None
    if then.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=then.tzinfo)
    elif then.tzinfo is None and now.tzinfo is not None:
        then = then.replace(tzinfo=now.tzinfo)
    return (now - then).total_seconds()


def run_check(repo_dir: Path, now: datetime, prior: dict | None = None,
              opener=_default_opener, timeout: float = _TIMEOUT,
              url: str = REMOTE_URL, throttle_seconds: float = THROTTLE_SECONDS) -> dict | None:
    """Produce the `update_check` block for state.json (or None on total failure).

    Block shape (all additive): {checked_at, local_head, remote_head, behind}.

      * local HEAD is read fresh EVERY call (cheap, local) so the banner clears the
        instant the user pulls — even inside the throttle window.
      * a real GitHub request happens only if the last one was >= throttle_seconds ago;
        otherwise the cached remote sha is reused (checked_at stays anchored to that
        last real fetch). EXCEPTION (#49): if local HEAD CHANGED since the prior
        check and mismatches the cached remote, the cache may simply be stale (the
        user pulled past it) — force one real fetch rather than show a false
        banner for up to the whole throttle window. A genuinely-behind clone has
        an UNCHANGED local, so it never refetches per-snapshot.
      * if the network fails, the cached remote is carried forward (keep nagging
        correctly) and checked_at is NOT advanced, so we retry on the next snapshot.
      * behind is always recomputed as local != remote, both present, AND HEAD on the
        main branch — a dev checkout on a feature branch (or detached HEAD) differs
        from remote main without being \"behind\", so it stays silent. Anything unknown
        -> behind False (silent, never a false banner).

    Never raises: any unexpected error yields None (leave the prior banner untouched)."""
    try:
        local = read_local_head(repo_dir)

        elapsed = _elapsed(prior, now)
        throttled = elapsed is not None and elapsed < throttle_seconds and bool(
            prior and prior.get("remote_head"))
        if (throttled and local
                and local != prior.get("local_head")
                and local != prior.get("remote_head")):
            throttled = False    # local moved past the cache — refresh before deciding (#49)

        if throttled:
            remote = prior["remote_head"]
            checked_at = prior["checked_at"]
        else:
            remote = fetch_remote_head(url=url, opener=opener, timeout=timeout)
            if remote is not None:
                checked_at = now.isoformat()
            else:
                # Fetch failed — reuse last-known remote, don't advance the window.
                remote = (prior or {}).get("remote_head")
                checked_at = (prior or {}).get("checked_at") or now.isoformat()

        on_main = read_head_branch(repo_dir) == "main"
        behind = bool(on_main and local and remote and local != remote)
        return {
            "checked_at": checked_at,
            "local_head": local,
            "remote_head": remote,
            "behind": behind,
        }
    except Exception:
        return None
