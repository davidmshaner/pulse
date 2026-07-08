"""test_frontend_common.py — the shared state→text painters. Manual-assert style."""
import sys
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent / 'src' / 'pulse'
sys.path.insert(0, str(WIDGET))
import frontend_common as fc  # noqa: E402

STATE = {
    "groups": [
        {"name": "Billable", "weekly_cap_h": 32, "monthly_cap_h": 128, "today_h": 1.0,
         "wtd": {"actual_h": 10.0, "hours_left": 22.0, "over": False},
         "7d": {"actual_h": 10.0}, "30d": {"actual_h": 40.0}},
    ],
    "engagements": {
        "Alpha": {"track_only": False, "weekly_cap_h": 8.0, "monthly_cap_h": 35, "today_h": 0.0,
                  "wtd": {"actual_h": 2.0, "hours_left": 6.0, "over": False},
                  "7d": {"actual_h": 2.0}, "30d": {"actual_h": 9.0}},
        "Personal": {"track_only": True, "weekly_cap_h": None, "monthly_cap_h": None, "today_h": 0.0,
                     "wtd": {"actual_h": 3.0}, "7d": {"actual_h": 3.0}, "30d": {"actual_h": 12.0}},
    },
    "live_bucket": {"bucket_path": ["Acme", "Alpha"], "last_active_minutes_ago": 3.0},
    "generated_at": "2026-06-09T11:00:00",
}


def test_title_uses_live_bucket_engagement():
    assert fc.title_for(STATE) == "Al 6h", fc.title_for(STATE)


def test_title_skips_track_only_live_bucket():
    s = dict(STATE)
    s["live_bucket"] = {"bucket_path": ["Personal"], "last_active_minutes_ago": 1.0}
    # Personal is track-only (no cap) -> falls through to the billable summary, not a crash.
    assert fc.title_for(s) == "✓ 6h", fc.title_for(s)


def test_title_none_is_pulse():
    assert fc.title_for(None) == "Pulse"


def test_bar_fills_proportionally():
    assert fc.bar(5, 10, width=10) == "█████·····", fc.bar(5, 10, width=10)


def test_menu_lines_groups_engagements_and_track_only():
    lines = fc.menu_lines(STATE)
    assert any("BILLABLE" in (l or "") for l in lines), lines
    assert any("Alpha" in (l or "") for l in lines), lines
    assert any("tracked, no cap" in (l or "") for l in lines), lines
    assert None in lines, "expected separator markers (None)"


# --- nested groups (issue #31) --------------------------------------------

NESTED_STATE = {
    "groups": [
        {"name": "All Work", "depth": 0, "weekly_cap_h": 40, "monthly_cap_h": 160,
         "today_h": 6.0, "wtd": {"actual_h": 22.0, "hours_left": 18.0, "over": False},
         "7d": {"actual_h": 23.0}, "30d": {"actual_h": 86.0}},
        {"name": "Billable", "depth": 1, "weekly_cap_h": 20, "monthly_cap_h": 80,
         "today_h": 3.0, "wtd": {"actual_h": 18.0, "hours_left": 2.0, "over": False},
         "7d": {"actual_h": 20.0}, "30d": {"actual_h": 70.0}},
        {"name": "Personal Software", "depth": 1, "weekly_cap_h": None,
         "monthly_cap_h": None, "today_h": 0.5,
         "wtd": {"actual_h": 4.0}, "7d": {"actual_h": 4.5}, "30d": {"actual_h": 16.0}},
    ],
    "engagements": {},
    "generated_at": "2026-07-08T11:00:00",
}


def test_menu_lines_nested_group_is_indented():
    lines = [l for l in fc.menu_lines(NESTED_STATE) if l]
    # the depth-1 sub-group's header line carries a leading indent the depth-0 one lacks
    top = [l for l in lines if "ALL WORK" in l][0]
    sub = [l for l in lines if "BILLABLE" in l][0]
    assert not top.startswith("  ●") and not top.startswith("   ")
    assert sub.startswith("  ")            # indented under its parent


def test_menu_lines_capless_group_shows_no_cap():
    lines = [l for l in fc.menu_lines(NESTED_STATE) if l]
    text = "\n".join(lines)
    assert "PERSONAL SOFTWARE" in text and "rolls up, no cap" in text
    # a capless group prints no "cap ...h/wk" line
    assert not any("PERSONAL SOFTWARE" in l and "h/wk" in l for l in lines)


def test_menu_lines_flat_group_unindented_and_capped():
    # the pre-nesting STATE (no depth key) still renders exactly as before
    lines = [l for l in fc.menu_lines(STATE) if l]
    head = [l for l in lines if "BILLABLE" in l][0]
    assert head.startswith("  BILLABLE")   # dot placeholder "  ", no extra indent
    assert "cap 32h/wk" in head


# --- income-meter mode (issue #38) ----------------------------------------

INCOME_STATE = {
    "engagements": {
        "MeterCap": {"income_mode": True, "bill_rate": 200, "monthly_cap_value": 10000,
                     "today_h": 1.5, "wtd": {"actual_h": 8.0}, "7d": {"actual_h": 9.0},
                     "30d": {"actual_h": 40.0},
                     "mtd": {"actual_h": 31.25, "billed": 6250, "dollars_left": 3750, "over": False}},
        "MeterOnly": {"income_mode": True, "bill_rate": 200, "monthly_cap_value": None,
                      "today_h": 0.5, "wtd": {"actual_h": 3.0}, "7d": {"actual_h": 4.0},
                      "30d": {"actual_h": 20.0},
                      "mtd": {"actual_h": 15.0, "billed": 3000}},
    },
    "generated_at": "2026-07-08T11:00:00",
}


def test_fmt_dollars_has_thousands_separator():
    assert fc.fmt_dollars(6250) == "$6,250"
    assert fc.fmt_dollars(10000) == "$10,000"


def test_menu_lines_income_cap_shows_dollars_and_remaining():
    lines = [l for l in fc.menu_lines(INCOME_STATE) if l]
    text = "\n".join(lines)
    assert "MeterCap" in text
    assert "$6,250" in text and "$10,000" in text
    assert "$3,750 left" in text
    # income rows must NOT print an hour cap line ("cap ...h/wk")
    assert not any("MeterCap" in l and "h/wk" in l for l in lines)


def test_menu_lines_income_pure_meter_shows_running_dollars_no_bar():
    lines = [l for l in fc.menu_lines(INCOME_STATE) if l]
    text = "\n".join(lines)
    assert "MeterOnly" in text
    assert "$3,000" in text
    # a pure meter has no ceiling, so no "/$" fraction and no left/over verdict
    assert not any("MeterOnly" in l for l in lines if "left" in l or "OVER" in l)


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
