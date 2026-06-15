"""test_calendar_discover.py — calendar credential discovery for setup (#10).

Pulse reuses existing Google OAuth credential files (the shape fetch_meetings
accepts: a *.json with a 'token' or 'refresh_token' key). Discovery is SHAPE-based,
not name-based, so it finds both the standard google_workspace_mcp layout AND
hand-rolled setups in custom dirs. It returns paths + tags only — never token
values (privacy, #8).
"""
import json
import sys
from pathlib import Path

SETUP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SETUP))
import discover  # noqa: E402


def _write_cred(d, keys, fname="creds.json"):
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(json.dumps(keys))


def test_validate_accepts_token_json(tmp_path):
    _write_cred(tmp_path, {"token": "abc", "client_id": "c"})
    assert discover.validate_cred_dir(tmp_path) is True


def test_validate_accepts_refresh_token_json(tmp_path):
    _write_cred(tmp_path, {"refresh_token": "r"})
    assert discover.validate_cred_dir(tmp_path) is True


def test_validate_rejects_non_credential_json(tmp_path):
    _write_cred(tmp_path, {"unrelated": "1"})
    assert discover.validate_cred_dir(tmp_path) is False


def test_validate_rejects_dir_without_json(tmp_path):
    (tmp_path / "sub").mkdir()
    assert discover.validate_cred_dir(tmp_path) is False


def test_validate_rejects_missing_dir(tmp_path):
    assert discover.validate_cred_dir(tmp_path / "nope") is False


def test_candidates_find_standard_and_handrolled(tmp_path):
    root = tmp_path / ".google_workspace_mcp"
    _write_cred(root / "credentials_offline", {"refresh_token": "r"})        # standard naming
    _write_cred(root / "my_custom_gcal", {"token": "t", "refresh_token": "r"})  # hand-rolled naming
    (root / "not_creds").mkdir(parents=True)
    (root / "not_creds" / "x.json").write_text('{"foo": 1}')                # ignored (wrong shape)

    cands = discover.cred_dir_candidates(search_roots=[root])
    by_name = {Path(c["credentials_dir"]).name: c["tag"] for c in cands}

    assert by_name.get("credentials_offline") == "offline", by_name  # tag strips 'credentials_'
    assert "my_custom_gcal" in by_name, "hand-rolled cred dir must be found by shape"
    assert "not_creds" not in by_name, "a dir without a token json must be excluded"


def test_validate_expands_user_path(tmp_path, monkeypatch):
    # The setup skill validates a user-typed path; '~/dir' (the natural shell form)
    # must expand, or a real hand-rolled cred dir is wrongly reported invalid.
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_cred(tmp_path / "acct", {"refresh_token": "r"})
    assert discover.validate_cred_dir("~/acct") is True


def test_tag_never_empty_for_bare_credentials_dir(tmp_path):
    _write_cred(tmp_path / "credentials_", {"token": "t"})
    cands = discover.cred_dir_candidates(search_roots=[tmp_path])
    tags = [c["tag"] for c in cands if Path(c["credentials_dir"]).name == "credentials_"]
    assert tags and tags[0], "tag must not be empty"


def test_candidates_never_leak_token_values(tmp_path):
    root = tmp_path / "creds"
    _write_cred(root / "acct", {"token": "SUPER_SECRET", "refresh_token": "r"})
    cands = discover.cred_dir_candidates(search_roots=[root])
    assert "SUPER_SECRET" not in json.dumps(cands), "discovery must not surface token values"
