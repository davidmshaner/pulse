"""test_staleness.py — the card must SHOW when its data is stale (#28).

When the refresh pipeline is killed before writing state.json, the card silently keeps
painting old numbers — David only noticed via a 2-hour-old value. frontend_common must
expose is_stale() and title_for() must mark a stale card so a frozen refresh is visible.

stdlib-only; no UI imports.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent / "src" / "pulse"
sys.path.insert(0, str(WIDGET))
import frontend_common as fc  # noqa: E402

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 17, 16, 0, 0, tzinfo=TZ)


def _gen(minutes_ago: int) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def _capped_state(generated_minutes_ago: int) -> dict:
    return {
        "generated_at": _gen(generated_minutes_ago),
        "engagements": {
            "SC": {"wtd": {"actual_h": 10.0, "hours_left": 22.0, "over": False}},
        },
    }


def test_is_stale_true_when_old():
    assert fc.is_stale(_capped_state(45), now=NOW) is True


def test_is_stale_false_when_fresh():
    assert fc.is_stale(_capped_state(5), now=NOW) is False


def test_is_stale_true_when_generated_at_missing():
    assert fc.is_stale({"engagements": {}}, now=NOW) is True


def test_is_stale_true_when_state_none():
    assert fc.is_stale(None, now=NOW) is True


def test_is_stale_handles_naive_generated_at_with_aware_now():
    # legacy/naive generated_at (no offset) + an aware injected now must not raise
    naive = {"generated_at": "2026-06-17T10:00:00"}  # naive, 6h before NOW
    assert fc.is_stale(naive, now=NOW) is True
    fresh_naive = {"generated_at": (NOW.replace(tzinfo=None)).isoformat(timespec="seconds")}
    assert fc.is_stale(fresh_naive, now=NOW) is False


def test_title_marks_stale_distinctly():
    state = _capped_state(5)
    fresh = fc.title_for(state, stale=False)
    stale = fc.title_for(state, stale=True)
    assert fresh != stale
    # the fresh signal is still present, just flagged as not-current
    assert stale.endswith(fresh) or fresh in stale


def test_title_for_default_is_unmarked():
    # back-compat: title_for(state) with no stale arg behaves as before
    state = _capped_state(5)
    assert fc.title_for(state) == fc.title_for(state, stale=False)
