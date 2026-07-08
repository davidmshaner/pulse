"""test_updatecheck.py — the "you're behind shanerconsulting/pulse main" detector.

Everything here is exercised WITHOUT a live GitHub call: the remote fetch takes an
injected opener, and local-HEAD reading is done against fake `.git` trees in tmp_path.
The whole module is contractually fail-silent — offline / 404 / timeout / garbage all
resolve to "no banner", never an exception into the menu-bar run loop (issue #25).
"""
import json
import sys
import pathlib
from datetime import datetime, timedelta, timezone
from urllib.error import URLError, HTTPError

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src" / "pulse"))
import updatecheck  # noqa: E402

SHA_A = "1111111111111111111111111111111111111111"
SHA_B = "2222222222222222222222222222222222222222"


# --- local HEAD reading ----------------------------------------------------

def _write(p: pathlib.Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_local_head_loose_ref(tmp_path):
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    _write(tmp_path / ".git" / "refs" / "heads" / "main", SHA_A + "\n")
    assert updatecheck.read_local_head(tmp_path) == SHA_A


def test_local_head_packed_ref(tmp_path):
    # No loose ref file — the sha lives only in packed-refs.
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    _write(tmp_path / ".git" / "packed-refs",
           "# pack-refs with: peeled fully-peeled sorted\n"
           f"{SHA_A} refs/heads/main\n"
           f"{SHA_B} refs/remotes/origin/main\n")
    assert updatecheck.read_local_head(tmp_path) == SHA_A


def test_local_head_detached(tmp_path):
    # Detached HEAD: the file holds a raw sha, not a symref.
    _write(tmp_path / ".git" / "HEAD", SHA_B + "\n")
    assert updatecheck.read_local_head(tmp_path) == SHA_B


def test_local_head_gitdir_pointer_file(tmp_path):
    # Submodule / worktree: .git is a FILE pointing at the real gitdir.
    real = tmp_path / "realgit"
    _write(real / "HEAD", "ref: refs/heads/main\n")
    _write(real / "refs" / "heads" / "main", SHA_A + "\n")
    _write(tmp_path / ".git", f"gitdir: {real}\n")
    assert updatecheck.read_local_head(tmp_path) == SHA_A


def test_local_head_missing_git_is_silent(tmp_path):
    assert updatecheck.read_local_head(tmp_path) is None


def test_local_head_garbage_is_silent(tmp_path):
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    # ref points nowhere — no loose file, no packed-refs
    assert updatecheck.read_local_head(tmp_path) is None


# --- remote HEAD fetch (injected opener) -----------------------------------

class _Resp:
    def __init__(self, body: bytes):
        self._body = body
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def close(self):
        pass


def _opener_ok(sha):
    def _open(url, timeout=None):
        return _Resp(json.dumps({"sha": sha, "commit": {}}).encode())
    return _open


def test_remote_head_success():
    assert updatecheck.fetch_remote_head(opener=_opener_ok(SHA_B)) == SHA_B


def test_remote_head_timeout_is_silent():
    def _open(url, timeout=None):
        raise TimeoutError("timed out")
    assert updatecheck.fetch_remote_head(opener=_open) is None


def test_remote_head_offline_is_silent():
    def _open(url, timeout=None):
        raise URLError("nodename nor servname provided")
    assert updatecheck.fetch_remote_head(opener=_open) is None


def test_remote_head_404_is_silent():
    def _open(url, timeout=None):
        raise HTTPError(url, 404, "Not Found", {}, None)
    assert updatecheck.fetch_remote_head(opener=_open) is None


def test_remote_head_malformed_json_is_silent():
    def _open(url, timeout=None):
        return _Resp(b"<html>rate limited</html>")
    assert updatecheck.fetch_remote_head(opener=_open) is None


def test_remote_head_missing_sha_key_is_silent():
    def _open(url, timeout=None):
        return _Resp(json.dumps({"message": "rate limit"}).encode())
    assert updatecheck.fetch_remote_head(opener=_open) is None


# --- run_check orchestration (throttle / carry-forward / fail-silent) -------

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def _patch_local(monkeypatch, sha, branch="main"):
    monkeypatch.setattr(updatecheck, "read_local_head", lambda repo_dir: sha)
    monkeypatch.setattr(updatecheck, "read_head_branch", lambda repo_dir: branch)


def test_run_check_behind_true(monkeypatch, tmp_path):
    _patch_local(monkeypatch, SHA_A)
    block = updatecheck.run_check(tmp_path, NOW, prior=None, opener=_opener_ok(SHA_B))
    assert block["behind"] is True
    assert block["local_head"] == SHA_A and block["remote_head"] == SHA_B
    assert block["checked_at"] == NOW.isoformat()


def test_run_check_feature_branch_is_silent(monkeypatch, tmp_path):
    # A dev checkout on a feature branch differs from remote main without being
    # "behind" — the banner must not fire (review finding on PR #45).
    _patch_local(monkeypatch, SHA_A, branch="issue-99")
    block = updatecheck.run_check(tmp_path, NOW, prior=None, opener=_opener_ok(SHA_B))
    assert block["behind"] is False


def test_run_check_detached_head_is_silent(monkeypatch, tmp_path):
    _patch_local(monkeypatch, SHA_A, branch=None)
    block = updatecheck.run_check(tmp_path, NOW, prior=None, opener=_opener_ok(SHA_B))
    assert block["behind"] is False


def test_read_head_branch(tmp_path):
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    assert updatecheck.read_head_branch(tmp_path) == "main"
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/issue-99\n")
    assert updatecheck.read_head_branch(tmp_path) == "issue-99"
    _write(tmp_path / ".git" / "HEAD", SHA_B + "\n")   # detached
    assert updatecheck.read_head_branch(tmp_path) is None


def test_run_check_current_is_silent(monkeypatch, tmp_path):
    _patch_local(monkeypatch, SHA_A)
    block = updatecheck.run_check(tmp_path, NOW, prior=None, opener=_opener_ok(SHA_A))
    assert block["behind"] is False


def test_run_check_offline_no_prior_is_silent(monkeypatch, tmp_path):
    _patch_local(monkeypatch, SHA_A)
    def _open(url, timeout=None):
        raise URLError("offline")
    block = updatecheck.run_check(tmp_path, NOW, prior=None, opener=_open)
    # Never fetched a remote and no cache — silent, never a false banner.
    assert block["behind"] is False


def test_run_check_throttled_skips_network(monkeypatch, tmp_path):
    _patch_local(monkeypatch, SHA_A)
    prior = {"checked_at": (NOW - timedelta(minutes=30)).isoformat(),
             "local_head": SHA_A, "remote_head": SHA_B, "behind": True}
    calls = []
    def _open(url, timeout=None):
        calls.append(url)
        return _Resp(json.dumps({"sha": SHA_A}).encode())
    block = updatecheck.run_check(tmp_path, NOW, prior=prior, opener=_open,
                                  throttle_seconds=6 * 3600)
    assert calls == []                          # within throttle window: no network
    assert block["remote_head"] == SHA_B        # carried from cache
    assert block["behind"] is True              # recomputed: local A != remote B
    assert block["checked_at"] == prior["checked_at"]   # window anchored to last real fetch


def test_run_check_throttle_recompute_clears_after_local_update(monkeypatch, tmp_path):
    # User pulled, so local now == the cached remote; banner must clear even though
    # we're inside the throttle window and skip the network.
    _patch_local(monkeypatch, SHA_B)
    prior = {"checked_at": (NOW - timedelta(minutes=10)).isoformat(),
             "local_head": SHA_A, "remote_head": SHA_B, "behind": True}
    block = updatecheck.run_check(tmp_path, NOW, prior=prior,
                                  opener=_opener_ok("SHOULD-NOT-BE-CALLED"),
                                  throttle_seconds=6 * 3600)
    assert block["behind"] is False


def test_run_check_stale_refetches(monkeypatch, tmp_path):
    _patch_local(monkeypatch, SHA_A)
    prior = {"checked_at": (NOW - timedelta(hours=12)).isoformat(),
             "local_head": SHA_A, "remote_head": SHA_A, "behind": False}
    block = updatecheck.run_check(tmp_path, NOW, prior=prior, opener=_opener_ok(SHA_B),
                                  throttle_seconds=6 * 3600)
    assert block["remote_head"] == SHA_B and block["behind"] is True
    assert block["checked_at"] == NOW.isoformat()       # window advanced on a real fetch


def test_run_check_fetch_fail_carries_prior_remote(monkeypatch, tmp_path):
    _patch_local(monkeypatch, SHA_A)
    prior = {"checked_at": (NOW - timedelta(hours=12)).isoformat(),
             "local_head": SHA_A, "remote_head": SHA_B, "behind": True}
    def _open(url, timeout=None):
        raise URLError("offline")
    block = updatecheck.run_check(tmp_path, NOW, prior=prior, opener=_open,
                                  throttle_seconds=6 * 3600)
    # Network failed this cycle: keep the last-known remote, keep nagging correctly,
    # and DON'T advance the window (so we retry next snapshot, not in 6h).
    assert block["remote_head"] == SHA_B and block["behind"] is True
    assert block["checked_at"] == prior["checked_at"]


def test_run_check_local_unreadable_is_silent(monkeypatch, tmp_path):
    _patch_local(monkeypatch, None)
    block = updatecheck.run_check(tmp_path, NOW, prior=None, opener=_opener_ok(SHA_B))
    # Can't read local HEAD -> can't say we're behind -> silent.
    assert block["behind"] is False


def test_run_check_never_raises(monkeypatch, tmp_path):
    # Even if read_local_head itself explodes, run_check swallows it (fail-silent).
    def _boom(repo_dir):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(updatecheck, "read_local_head", _boom)
    block = updatecheck.run_check(tmp_path, NOW, prior=None, opener=_opener_ok(SHA_B))
    assert block is None or block["behind"] is False


# --- stale-cache false positive (#49) ----------------------------------------

SHA_C = "3333333333333333333333333333333333333333"


def test_pull_past_stale_cached_remote_forces_fresh_fetch(monkeypatch, tmp_path):
    # The user pulled PAST the cached remote sha (remote advanced since the last
    # real fetch). Plain inequality against the stale cache showed a false
    # banner that survived its own update command (#49). Local changed since
    # the prior check + mismatches the cache -> force a real fetch.
    _patch_local(monkeypatch, SHA_C)                     # local moved to newest main
    prior = {"checked_at": (NOW - timedelta(minutes=30)).isoformat(),
             "local_head": SHA_A, "remote_head": SHA_B, "behind": True}
    calls = []
    def _open(url, timeout=None):
        calls.append(url)
        return _Resp(json.dumps({"sha": SHA_C}).encode())  # real remote == local now
    block = updatecheck.run_check(tmp_path, NOW, prior=prior, opener=_open,
                                  throttle_seconds=6 * 3600)
    assert calls, "must bypass the throttle when local changed past the cached remote"
    assert block["behind"] is False
    assert block["remote_head"] == SHA_C
    assert block["checked_at"] == NOW.isoformat()        # window re-anchored to the real fetch


def test_unchanged_local_still_behind_keeps_cache_no_refetch(monkeypatch, tmp_path):
    # A genuinely-behind clone (local UNCHANGED since prior check) must keep the
    # cached compare — no network every 10-min snapshot (anon rate limit).
    _patch_local(monkeypatch, SHA_A)
    prior = {"checked_at": (NOW - timedelta(minutes=30)).isoformat(),
             "local_head": SHA_A, "remote_head": SHA_B, "behind": True}
    calls = []
    def _open(url, timeout=None):
        calls.append(url)
        return _Resp(json.dumps({"sha": SHA_B}).encode())
    block = updatecheck.run_check(tmp_path, NOW, prior=prior, opener=_open,
                                  throttle_seconds=6 * 3600)
    assert calls == []
    assert block["behind"] is True


def test_forced_refetch_failure_is_silent_and_retries(monkeypatch, tmp_path):
    # If the FORCED refresh fails, the cache is known-suspect: never show the
    # (possibly false) banner, and keep the prior local_head so the bypass
    # re-fires next snapshot — retrying until a real fetch settles it.
    _patch_local(monkeypatch, SHA_C)
    prior = {"checked_at": (NOW - timedelta(minutes=30)).isoformat(),
             "local_head": SHA_A, "remote_head": SHA_B, "behind": True}
    def _down(url, timeout=None):
        raise URLError("offline")
    block = updatecheck.run_check(tmp_path, NOW, prior=prior, opener=_down,
                                  throttle_seconds=6 * 3600)
    assert block["behind"] is False                      # suspect cache -> silent
    assert block["remote_head"] == SHA_B                 # carried forward
    assert block["checked_at"] == prior["checked_at"]    # window not advanced
    assert block["local_head"] == SHA_A                  # bypass re-arms next tick

    # Next snapshot, network back: bypass re-fires and settles the truth.
    calls = []
    def _up(url, timeout=None):
        calls.append(url)
        return _Resp(json.dumps({"sha": SHA_C}).encode())
    nxt = updatecheck.run_check(tmp_path, NOW + timedelta(minutes=10), prior=block,
                                opener=_up, throttle_seconds=6 * 3600)
    assert calls and nxt["behind"] is False and nxt["remote_head"] == SHA_C


def test_bypass_gated_on_main_no_wasted_fetch(monkeypatch, tmp_path):
    # Off-main the banner is forced silent, so HEAD churn on a feature branch
    # must NOT burn a fetch per snapshot inside the throttle window.
    _patch_local(monkeypatch, SHA_C, branch="issue-99")
    prior = {"checked_at": (NOW - timedelta(minutes=30)).isoformat(),
             "local_head": SHA_A, "remote_head": SHA_B, "behind": False}
    calls = []
    def _open(url, timeout=None):
        calls.append(url)
        return _Resp(json.dumps({"sha": SHA_C}).encode())
    block = updatecheck.run_check(tmp_path, NOW, prior=prior, opener=_open,
                                  throttle_seconds=6 * 3600)
    assert calls == [] and block["behind"] is False
