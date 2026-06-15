"""test_install_guard.py — install-mac.sh must refuse a TCC-protected clone
location (#16) with a clear message BEFORE doing any work, instead of writing a
plist that crash-loops the LaunchAgent with an opaque 'Operation not permitted'.

macOS TCC denies launchd's python read access to ~/Documents, ~/Desktop,
~/Downloads, iCloud Drive, and the cloud providers under ~/Library/CloudStorage.
The matching is case-insensitive (the default macOS volume is) and covers the
physical path. `install-mac.sh --check` runs only the preflight, so these tests
are hermetic and fast — they never reach pip / plist / launchctl.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parent.parent / "install-mac.sh"

# Clone locations the guard must refuse (relative to a fake $HOME).
PROTECTED = [
    "Documents/pulse",
    "Desktop/pulse",
    "Downloads/pulse",
    "documents/pulse",                                       # case-insensitive volume
    "Library/Mobile Documents/com~apple~CloudDocs/pulse",    # iCloud Drive
    "Library/CloudStorage/Dropbox-Personal/pulse",           # third-party cloud mount
]
# Clone locations the guard must allow (must NOT be a false positive).
SAFE = ["dev/pulse", "projects/pulse", "pulse"]


def _check(rel: str, home: Path) -> subprocess.CompletedProcess:
    """Copy install-mac.sh into $HOME/<rel> and run `--check` (preflight only)."""
    repo = home / rel
    repo.mkdir(parents=True, exist_ok=True)
    shutil.copy(INSTALLER, repo / "install-mac.sh")
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(
        ["bash", str(repo / "install-mac.sh"), "--check"],
        env=env, capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("rel", PROTECTED)
def test_refuses_tcc_protected_location(tmp_path, rel):
    res = _check(rel, tmp_path / "home")
    assert res.returncode == 1, f"should refuse {rel!r}; stdout={res.stdout}"
    out = (res.stdout + res.stderr).lower()
    assert ("tcc" in out or "protected" in out or "operation not permitted" in out), \
        f"expected a clear TCC-location message; got:\n{res.stdout}\n{res.stderr}"


@pytest.mark.parametrize("rel", SAFE)
def test_allows_safe_location(tmp_path, rel):
    res = _check(rel, tmp_path / "home")
    assert res.returncode == 0, f"should allow {rel!r}; stderr={res.stderr}"
