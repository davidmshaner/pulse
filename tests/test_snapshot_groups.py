#!/usr/bin/env python3
"""test_snapshot_groups.py — pure helpers behind groups + track-only engagements.

engagement_caps resolves the three cap modes; _group_overlap flags the
parent-contains-child double-count trap. Both are pure (no I/O).

Run: python3 tests/test_snapshot_groups.py
"""
from __future__ import annotations

import sys
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent / 'src' / 'pulse'
sys.path.insert(0, str(WIDGET))

from snapshot import engagement_caps, _group_overlap, apply_remainder, WEEKS_PER_MONTH  # noqa: E402


def _approx(a, b, eps=1e-6):
    return abs(a - b) < eps


def test_caps_rate_mode():
    wk, mo = engagement_caps({"monthly_value": 5000, "target_rate": 250})
    assert _approx(mo, 20.0) and _approx(wk, 20.0 / WEEKS_PER_MONTH)


def test_caps_hours_weekly_only_derives_monthly():
    wk, mo = engagement_caps({"weekly_hours": 8})
    assert wk == 8.0 and _approx(mo, 8.0 * WEEKS_PER_MONTH)


def test_caps_hours_monthly_only_derives_weekly():
    wk, mo = engagement_caps({"monthly_hours": 100})
    assert mo == 100.0 and _approx(wk, 100.0 / WEEKS_PER_MONTH)


def test_caps_hours_both_explicit():
    assert engagement_caps({"weekly_hours": 8, "monthly_hours": 35}) == (8.0, 35.0)


def test_caps_track_only_is_none():
    assert engagement_caps({}) == (None, None)
    assert engagement_caps({"bucket": "personal"}) == (None, None)


def test_overlap_disjoint_leaves_ok():
    est = {"Metis": {"bucket": "Metis"}, "GI": {"bucket": "GI"}}
    rolled = {"SC.Metis": 60.0, "SC.GI": 30.0, "SC": 90.0}
    assert _group_overlap(["Metis", "GI"], est, rolled) == []


def test_overlap_parent_contains_child_flagged():
    est = {"SC": {"bucket": "SC"}, "Metis": {"bucket": "Metis"}}
    rolled = {"SC": 90.0, "SC.Metis": 60.0}
    warns = _group_overlap(["SC", "Metis"], est, rolled)
    assert len(warns) == 1 and "SC" in warns[0] and "Metis" in warns[0]


def test_apply_remainder_subtracts_only_descendants():
    est = {
        "Shaner Consulting": {"bucket": "SC", "today_h": 2.0,
                              "wtd": {"actual_h": 38.09}, "7d": {"actual_h": 38.93}, "30d": {"actual_h": 120.0}},
        "GI":       {"bucket": "GI", "today_h": 1.0,
                     "wtd": {"actual_h": 29.20}, "7d": {"actual_h": 29.20}, "30d": {"actual_h": 90.0}},
        "Redacted": {"bucket": "Redacted", "today_h": 0.0,
                     "wtd": {"actual_h": 3.07}, "7d": {"actual_h": 3.87}, "30d": {"actual_h": 10.0}},
        "Personal": {"bucket": "personal", "today_h": 0.5,
                     "wtd": {"actual_h": 4.16}, "7d": {"actual_h": 5.17}, "30d": {"actual_h": 20.0}},
    }
    canon = {"Shaner Consulting": "SC", "GI": "SC.GI", "Redacted": "SC.Redacted", "Personal": "personal"}
    apply_remainder(est, canon, ["Shaner Consulting"])
    sc = est["Shaner Consulting"]
    assert sc["wtd"]["actual_h"] == 5.82                 # 38.09 - 29.20 - 3.07
    assert sc["remainder"] is True
    assert set(sc["remainder_minus"]) == {"GI", "Redacted"}   # Personal is NOT under SC
    assert est["Personal"]["wtd"]["actual_h"] == 4.16   # untouched


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
