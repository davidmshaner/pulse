"""test_config.py — verifies the config seam resolves the expected machine paths.
Manual-assert style (matches test_snapshot_overlap.py). Run: python3 tests/test_config.py"""
import sys
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent / 'src' / 'pulse'
sys.path.insert(0, str(WIDGET))

import config  # noqa: E402


def test_projects_dirs_resolve_absolute():
    # Portable contract: every configured projects dir resolves to an absolute
    # path (relative entries resolve against home). No machine-specific dir asserted.
    assert config.PROJECTS_DIRS, "expected at least one projects dir"
    for p in config.PROJECTS_DIRS:
        assert p.is_absolute(), p


def test_cowork_root_is_local_agent_sessions():
    assert config.COWORK_ROOT.name == "local-agent-mode-sessions", config.COWORK_ROOT


def test_timezone_is_eastern():
    assert str(config.LOCAL_TZ) == "America/New_York", config.LOCAL_TZ


def test_timecore_dir_importable():
    assert config.TIMECORE_DIR.is_dir(), config.TIMECORE_DIR
    sys.path.insert(0, str(config.TIMECORE_DIR))
    from time_math import compute_bucket_times  # noqa: F401
    from classify import walk_registry  # noqa: F401


def test_categorization_inputs_decoupled_from_deploy_week():
    # Standalone contract: registry/learnings/rules resolve to absolute paths
    # (repo-local by default, user-overridable), and config no longer hardcodes a
    # deploy-week checkout. A clean clone has neither SCRIPTS nor DEPLOY_WEEK.
    for p in (config.REGISTRY, config.LEARNINGS, config.RULES, config.OVERRIDES):
        assert p.is_absolute(), p
    assert not hasattr(config, "DEPLOY_WEEK"), "config still exposes DEPLOY_WEEK"
    assert not hasattr(config, "SCRIPTS"), "config still exposes SCRIPTS"


def test_calendar_config_shape():
    # Calendar is config-driven: a list of self-emails and (tag, cred_dir) accounts.
    # Empty when unconfigured; populated when the user wires accounts.
    assert isinstance(config.CALENDAR_SELF_EMAILS, list)
    assert isinstance(config.CALENDAR_ACCOUNTS, list)
    for tag, cred in config.CALENDAR_ACCOUNTS:
        assert isinstance(tag, str), tag
        assert isinstance(cred, Path), cred


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {t.__name__}\n  {e}")
        except Exception as e:
            failed += 1; print(f"ERROR {t.__name__}\n  {type(e).__name__}: {e}")
    print(f"\n=== {failed}/{len(tests)} FAILED ===" if failed else f"=== all {len(tests)} passed ===")
    sys.exit(1 if failed else 0)
