"""test_cred_shape_agreement.py — discover._has_cred_file (setup) and
fetch_meetings.load_creds (runtime) encode the same credential-shape rule in two
files. This pins them together: a dir the setup skill accepts must be one the
fetcher can actually load, and vice versa. Catches silent drift between them.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "setup"))
sys.path.insert(0, str(ROOT / "src" / "pulse"))

import discover        # noqa: E402
import fetch_meetings  # noqa: E402


def _mk(d, keys):
    d.mkdir(parents=True, exist_ok=True)
    (d / "creds.json").write_text(json.dumps(keys))
    return d


def test_both_accept_a_token_dir(tmp_path):
    d = _mk(tmp_path / "ok", {"token": "t", "refresh_token": "r", "client_id": "c"})
    assert discover.validate_cred_dir(d) is True
    data, _ = fetch_meetings.load_creds(d)
    assert data is not None


def test_both_reject_a_non_credential_dir(tmp_path):
    d = _mk(tmp_path / "bad", {"unrelated": 1})
    assert discover.validate_cred_dir(d) is False
    data, _ = fetch_meetings.load_creds(d)
    assert data is None
