#!/usr/bin/env python3
"""test_snapshot_overlap.py — regression test for session/meeting overlap math.

snapshot.py:per_path_minutes must add meeting minutes into the SAME sweep-line as
sessions (not as scalars after even_split_fractional collapses sessions), or it
double-counts overlap in 5 scenarios (modes 1-5 below).

_compose_per_path_minutes is the pure-function unit-testable target. Bucket names
here (Acme/Alpha/Beta) are arbitrary labels for the math.

Run: python3 tests/test_snapshot_overlap.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

WIDGET = Path(__file__).resolve().parent.parent / 'src' / 'pulse'
sys.path.insert(0, str(WIDGET))

from snapshot import _compose_per_path_minutes  # noqa: E402

LOCAL_TZ = ZoneInfo("America/New_York")
A = ("Acme", "Alpha")
B = ("Acme", "Beta")


def D(h: int, m: int) -> datetime:
    return datetime(2026, 5, 29, h, m, tzinfo=LOCAL_TZ)


def meet(bp: tuple, start: datetime, end: datetime) -> dict:
    return {"bucket_path": list(bp), "start": start.isoformat(), "end": end.isoformat()}


def run(pb_sessions: dict, meetings: list, window=(D(0, 0), D(23, 59))) -> dict:
    return _compose_per_path_minutes(pb_sessions, meetings, window[0], window[1], LOCAL_TZ)


def assert_close(actual: dict, expected: dict, case: str):
    keys = set(actual) | set(expected)
    for k in keys:
        a = actual.get(k, 0.0)
        e = expected.get(k, 0.0)
        assert abs(a - e) < 0.5, (
            f"{case}: at {k}: expected ~{e:.1f}m, got {a:.1f}m  (Δ={a-e:+.1f})\n"
            f"  full actual:   {actual}\n  full expected: {expected}"
        )


# ============================================================================
# FAILING TESTS — these expose the bug. Pre-fix: 5 fail. Post-fix: 5 pass.
# ============================================================================

def test_mode1_same_bucket_session_inside_meeting():
    """Alpha session 9:10-9:40 entirely inside Alpha meeting 9-11. Wall-clock =
    120m (meeting alone). Buggy code: 30 + 120 = 150m. Fix → 120m."""
    out = run(
        pb_sessions={A: [(D(9, 10), D(9, 40))]},
        meetings=[meet(A, D(9, 0), D(11, 0))],
    )
    assert_close(out, {"Acme": 120.0, "Acme.Alpha": 120.0}, "mode1")
    print("  PASS  mode 1: same-bucket session inside meeting → wall-clock 120m")


def test_mode2_cross_bucket_session_during_meeting():
    """Beta session 9-10 in parallel with Alpha meeting 9-10. Wall-clock = 60m of
    life, split between two concurrent buckets → 30m each. Buggy code: 60+60."""
    out = run(
        pb_sessions={B: [(D(9, 0), D(10, 0))]},
        meetings=[meet(A, D(9, 0), D(10, 0))],
    )
    assert_close(out, {"Acme": 60.0, "Acme.Alpha": 30.0, "Acme.Beta": 30.0}, "mode2")
    print("  PASS  mode 2: cross-bucket session × meeting → 30m each (even-split)")


def test_mode3_two_meetings_same_bucket_overlapping():
    """Two Alpha meetings 9-10 and 9:30-10:30 (calendar double-book). Wall-clock
    union = 90m. Buggy code: 60+60 = 120m."""
    out = run(
        pb_sessions={},
        meetings=[meet(A, D(9, 0), D(10, 0)), meet(A, D(9, 30), D(10, 30))],
    )
    assert_close(out, {"Acme": 90.0, "Acme.Alpha": 90.0}, "mode3")
    print("  PASS  mode 3: two overlapping same-bucket meetings → wall-clock 90m")


def test_mode4_cross_bucket_meetings_overlapping():
    """Alpha meeting 9-10 + Beta meeting 9:30-10:30. Wall-clock = 90m of life.
    9-9:30 is Alpha-only (30m). 9:30-10 is concurrent → split (15+15). 10-10:30 is
    Beta-only (30m). Total: Alpha=45, Beta=45, Acme=90."""
    out = run(
        pb_sessions={},
        meetings=[meet(A, D(9, 0), D(10, 0)), meet(B, D(9, 30), D(10, 30))],
    )
    assert_close(out, {"Acme": 90.0, "Acme.Alpha": 45.0, "Acme.Beta": 45.0}, "mode4")
    print("  PASS  mode 4: cross-bucket overlapping meetings → even-split overlap")


def test_mode5_session_extends_past_meeting():
    """Alpha session 9-11 with Alpha meeting 10-11 inside it. Wall-clock = 120m
    (just the session, meeting fully inside). Buggy code: 120 + 60 = 180m."""
    out = run(
        pb_sessions={A: [(D(9, 0), D(11, 0))]},
        meetings=[meet(A, D(10, 0), D(11, 0))],
    )
    assert_close(out, {"Acme": 120.0, "Acme.Alpha": 120.0}, "mode5")
    print("  PASS  mode 5: session extends past meeting → wall-clock 120m")


# ============================================================================
# REGRESSION GUARDS — these pass both pre-fix and post-fix. Their job is to
# catch a fix that over-rotates and breaks non-overlap cases.
# ============================================================================

def test_rg1_same_bucket_no_overlap():
    """Alpha meeting 9-10, Alpha session 14-15. No overlap → 60+60 = 120m."""
    out = run(
        pb_sessions={A: [(D(14, 0), D(15, 0))]},
        meetings=[meet(A, D(9, 0), D(10, 0))],
    )
    assert_close(out, {"Acme": 120.0, "Acme.Alpha": 120.0}, "rg1")
    print("  PASS  RG-1: same-bucket non-overlap stays additive")


def test_rg2_meeting_alone():
    out = run(pb_sessions={}, meetings=[meet(A, D(9, 0), D(10, 0))])
    assert_close(out, {"Acme": 60.0, "Acme.Alpha": 60.0}, "rg2")
    print("  PASS  RG-2: meeting alone → meeting duration")


def test_rg3_session_alone():
    out = run(pb_sessions={A: [(D(9, 0), D(10, 0))]}, meetings=[])
    assert_close(out, {"Acme": 60.0, "Acme.Alpha": 60.0}, "rg3")
    print("  PASS  RG-3: session alone unchanged")


def test_rg4_two_meetings_same_bucket_non_overlap():
    out = run(
        pb_sessions={},
        meetings=[meet(A, D(9, 0), D(10, 0)), meet(A, D(14, 0), D(15, 0))],
    )
    assert_close(out, {"Acme": 120.0, "Acme.Alpha": 120.0}, "rg4")
    print("  PASS  RG-4: two non-overlapping same-bucket meetings sum")


def test_rg5_cross_bucket_sessions_no_overlap():
    out = run(
        pb_sessions={A: [(D(9, 0), D(10, 0))], B: [(D(14, 0), D(15, 0))]},
        meetings=[],
    )
    assert_close(out, {"Acme": 120.0, "Acme.Alpha": 60.0, "Acme.Beta": 60.0}, "rg5")
    print("  PASS  RG-5: cross-bucket non-overlap sessions sum")


def test_rg6_cross_bucket_meetings_no_overlap():
    out = run(
        pb_sessions={},
        meetings=[meet(A, D(9, 0), D(10, 0)), meet(B, D(14, 0), D(15, 0))],
    )
    assert_close(out, {"Acme": 120.0, "Acme.Alpha": 60.0, "Acme.Beta": 60.0}, "rg6")
    print("  PASS  RG-6: cross-bucket non-overlap meetings sum")


# ============================================================================
# TZ HANDLING — meetings can be naive (all-day) or tz-aware (timed). The
# helper must normalize before mixing with tz-aware session intervals.
# ============================================================================

def test_tz_naive_meeting_normalized_to_local():
    """A meeting with a naive datetime (all-day events sometimes serialize this
    way) must not blow up merge_intervals comparisons against tz-aware sessions."""
    naive_start = datetime(2026, 5, 29, 9, 0)
    naive_end = datetime(2026, 5, 29, 10, 0)
    m = {"bucket_path": list(A), "start": naive_start.isoformat(), "end": naive_end.isoformat()}
    out = run(pb_sessions={A: [(D(14, 0), D(15, 0))]}, meetings=[m])
    assert_close(out, {"Acme": 120.0, "Acme.Alpha": 120.0}, "tz-naive")
    print("  PASS  TZ: naive meeting datetimes normalized without blowup")


if __name__ == "__main__":
    failing_tests = [
        test_mode1_same_bucket_session_inside_meeting,
        test_mode2_cross_bucket_session_during_meeting,
        test_mode3_two_meetings_same_bucket_overlapping,
        test_mode4_cross_bucket_meetings_overlapping,
        test_mode5_session_extends_past_meeting,
    ]
    regression_guards = [
        test_rg1_same_bucket_no_overlap,
        test_rg2_meeting_alone,
        test_rg3_session_alone,
        test_rg4_two_meetings_same_bucket_non_overlap,
        test_rg5_cross_bucket_sessions_no_overlap,
        test_rg6_cross_bucket_meetings_no_overlap,
        test_tz_naive_meeting_normalized_to_local,
    ]
    failures = []
    print("FAILING-MODE TESTS (these expose the bug — must pass after fix):")
    for t in failing_tests:
        try:
            t()
        except AssertionError as e:
            failures.append((t.__name__, str(e)))
            print(f"  FAIL  {t.__name__}\n    {e}")
    print()
    print("REGRESSION GUARDS (these must pass before AND after the fix):")
    for t in regression_guards:
        try:
            t()
        except AssertionError as e:
            failures.append((t.__name__, str(e)))
            print(f"  FAIL  {t.__name__}\n    {e}")
    print()
    total = len(failing_tests) + len(regression_guards)
    if failures:
        print(f"=== {len(failures)}/{total} FAILED ===")
        sys.exit(1)
    print(f"=== all {total} passed ===")
