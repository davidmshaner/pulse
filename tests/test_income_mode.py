#!/usr/bin/env python3
"""test_income_mode.py — the income-meter engagement flavor (#38).

`bill_rate` selects income mode: the card meters cumulative $ billed for the
CALENDAR MONTH ($ = MTD actual hours × bill_rate), with an optional
`monthly_cap_value` ceiling — the inverse of rate-mode (which divides $ into an
hour cap). These are pure helpers (no I/O), so no pyobjc/network here.

Run: python3 tests/test_income_mode.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

WIDGET = Path(__file__).resolve().parent.parent / "src" / "pulse"
sys.path.insert(0, str(WIDGET))

from snapshot import (  # noqa: E402
    appetite_errors,
    dollars_remaining_or_over,
    engagement_caps,
    income_billed,
    is_income_mode,
    month_start,
)


def _approx(a, b, eps=1e-6):
    return abs(a - b) < eps


# --- mode detection --------------------------------------------------------

def test_is_income_mode_true_when_bill_rate_present():
    assert is_income_mode({"bill_rate": 200}) is True
    assert is_income_mode({"bill_rate": 200, "monthly_cap_value": 10000}) is True


def test_is_income_mode_false_for_other_flavors():
    assert is_income_mode({"monthly_value": 5000, "target_rate": 250}) is False
    assert is_income_mode({"weekly_hours": 8}) is False
    assert is_income_mode({"bucket": "personal"}) is False
    assert is_income_mode({}) is False


def test_income_mode_is_not_resolved_to_an_hour_cap():
    # An income engagement must NOT fall through engagement_caps into a bar —
    # main() handles it separately. engagement_caps sees no cap keys -> (None, None).
    assert engagement_caps({"bill_rate": 200}) == (None, None)


# --- billed math -----------------------------------------------------------

def test_income_billed_is_hours_times_rate():
    assert _approx(income_billed(25.0, 250), 6250.0)
    assert _approx(income_billed(0.0, 200), 0.0)
    assert _approx(income_billed(31.25, 200), 6250.0)


def test_dollars_remaining_under_cap():
    d = dollars_remaining_or_over(6000.0, 7500.0)
    assert d["over"] is False and d["dollars_left"] == 1500.0
    assert "dollars_over" not in d


def test_dollars_over_cap():
    d = dollars_remaining_or_over(9000.0, 7500.0)
    assert d["over"] is True and d["dollars_over"] == 1500.0
    assert "dollars_left" not in d


def test_dollars_exactly_at_cap_is_not_over():
    d = dollars_remaining_or_over(7500.0, 7500.0)
    assert d["over"] is False and d["dollars_left"] == 0.0


# --- MTD window (calendar month-to-date, resets on the 1st) -----------------

def test_month_start_is_first_of_month_midnight_local():
    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 7, 8, 15, 30, tzinfo=tz)
    ms = month_start(now)
    assert (ms.year, ms.month, ms.day) == (2026, 7, 1)
    assert (ms.hour, ms.minute, ms.second, ms.microsecond) == (0, 0, 0, 0)
    assert ms.tzinfo == now.tzinfo


# --- config validation (loud preflight, never a silent miscount) -----------

def test_appetite_errors_flags_income_rate_mix():
    errs = appetite_errors({"Bad": {"bill_rate": 200, "monthly_value": 5000, "target_rate": 250}})
    assert len(errs) == 1
    assert "Bad" in errs[0]
    assert "bill_rate" in errs[0] and "monthly_value" in errs[0]


def test_appetite_errors_flags_income_hours_mix():
    errs = appetite_errors({"Bad": {"bill_rate": 200, "weekly_hours": 8}})
    assert len(errs) == 1 and "Bad" in errs[0]


def test_appetite_errors_flags_cap_without_rate():
    errs = appetite_errors({"Bad": {"monthly_cap_value": 10000}})
    assert len(errs) == 1 and "monthly_cap_value" in errs[0]


def test_appetite_errors_clean_configs_pass():
    clean = {
        "MeterOnly":  {"bill_rate": 200},
        "MeterCap":   {"bill_rate": 200, "monthly_cap_value": 10000},
        "RateMode":   {"monthly_value": 5000, "target_rate": 250},
        "HoursMode":  {"weekly_hours": 8},
        "TrackOnly":  {"bucket": "personal"},
    }
    assert appetite_errors(clean) == []


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
