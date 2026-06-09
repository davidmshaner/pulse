"""test_discover.py — unit tests for the setup discovery helper. Manual-assert style.
Run: python3 setup/tests/test_discover.py"""
import sys
from pathlib import Path

SETUP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SETUP))
import discover  # noqa: E402


def test_decode_encoded_roundtrips_real_path(tmp=Path.home()):
    # An encoded name for the home dir decodes back to a real, existing path.
    enc = str(tmp).replace("/", "-")
    assert discover.decode_project_dir(enc) == tmp, (enc, discover.decode_project_dir(enc))


def test_decode_unresolvable_returns_none():
    assert discover.decode_project_dir("-nonexistent-path-xyz-123") is None


def test_detect_os_is_known():
    assert discover.detect_os() in ("macos", "windows", "linux")


def test_cowork_dir_for_macos_shape():
    p = discover.cowork_dir_for("macos")
    assert p.name == "local-agent-mode-sessions", p


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {t.__name__}\n  {e}")
    print(f"\n=== {failed}/{len(tests)} FAILED ===" if failed else f"=== all {len(tests)} passed ===")
    sys.exit(1 if failed else 0)
