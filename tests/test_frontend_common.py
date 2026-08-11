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


# --- nested engagement rows (issue #66) -----------------------------------
# menu_lines interleaves engagement members into their group's subtree with an
# indent one level deeper than the parent; unclaimed engagements stay flat at
# the end. iter_rows is the shared walk both frontends consume.

MEMBER_STATE = {
    "groups": [
        {"name": "All Work", "depth": 0, "weekly_cap_h": 40, "monthly_cap_h": 160,
         "today_h": 6.0, "wtd": {"actual_h": 22.0, "hours_left": 18.0, "over": False},
         "7d": {"actual_h": 23.0}, "30d": {"actual_h": 86.0},
         "direct_engagements": []},
        {"name": "Billable", "depth": 1, "weekly_cap_h": 20, "monthly_cap_h": 80,
         "today_h": 3.0, "wtd": {"actual_h": 18.0, "hours_left": 2.0, "over": False},
         "7d": {"actual_h": 20.0}, "30d": {"actual_h": 70.0},
         "direct_engagements": ["ClientA"]},
    ],
    "engagements": {
        "ClientA": {"track_only": False, "weekly_cap_h": 8.0, "monthly_cap_h": 35, "today_h": 0.0,
                    "wtd": {"actual_h": 2.0, "hours_left": 6.0, "over": False},
                    "7d": {"actual_h": 2.0}, "30d": {"actual_h": 9.0}},
        "Loose": {"track_only": True, "weekly_cap_h": None, "monthly_cap_h": None, "today_h": 0.0,
                  "wtd": {"actual_h": 3.0}, "7d": {"actual_h": 3.0}, "30d": {"actual_h": 12.0}},
    },
    "generated_at": "2026-08-11T11:00:00",
}


def test_iter_rows_interleaves_members_after_subtree():
    rows = [(k, n, d) for k, n, _, d in fc.iter_rows(MEMBER_STATE)]
    assert rows == [("group", "All Work", 0), ("group", "Billable", 1),
                    ("engagement", "ClientA", 2), ("engagement", "Loose", 0)], rows


def test_iter_rows_legacy_total_fallback():
    legacy = {"total": {"weekly_cap_h": 32, "monthly_cap_h": 128, "today_h": 0.0,
                        "wtd": {"actual_h": 1.0, "hours_left": 31.0, "over": False},
                        "7d": {"actual_h": 1.0}, "30d": {"actual_h": 4.0}},
              "engagements": {}}
    rows = [(k, n, d) for k, n, _, d in fc.iter_rows(legacy)]
    assert rows == [("group", "Billable", 0)]


def test_menu_lines_member_engagement_indented_inside_group():
    lines = fc.menu_lines(MEMBER_STATE)
    txt = [l for l in lines if l]
    client = [l for l in txt if "ClientA" in l][0]
    assert client.startswith("    ")                    # depth 2 -> two indent stops
    idx = {name: next(i for i, l in enumerate(txt) if name in l)
           for name in ("BILLABLE", "ClientA", "Loose")}
    assert idx["BILLABLE"] < idx["ClientA"] < idx["Loose"]


def test_menu_lines_unclaimed_engagement_stays_flat():
    lines = [l for l in fc.menu_lines(MEMBER_STATE) if l]
    loose = [l for l in lines if "Loose" in l][0]
    assert loose.startswith("  Loose")                  # today's exact un-nested line


def test_iter_rows_deepest_listing_parent_wins():
    # An engagement listed by BOTH a parent and its sub-group nests under the
    # sub-group (most-specific), not the first-visited outer group.
    s = {"groups": [
            {"name": "Billable", "depth": 0, "weekly_cap_h": 20, "monthly_cap_h": 80,
             "today_h": 0.0, "wtd": {"actual_h": 5.0, "hours_left": 15.0, "over": False},
             "7d": {"actual_h": 5.0}, "30d": {"actual_h": 20.0},
             "direct_engagements": ["ClientA", "ClientB"]},
            {"name": "Sub", "depth": 1, "weekly_cap_h": None, "monthly_cap_h": None,
             "track_only": True, "today_h": 0.0, "wtd": {"actual_h": 2.0},
             "7d": {"actual_h": 2.0}, "30d": {"actual_h": 8.0},
             "direct_engagements": ["ClientA"]},
         ],
         "engagements": {
            "ClientA": {"track_only": True, "weekly_cap_h": None, "monthly_cap_h": None,
                        "today_h": 0.0, "wtd": {"actual_h": 2.0},
                        "7d": {"actual_h": 2.0}, "30d": {"actual_h": 8.0}},
            "ClientB": {"track_only": True, "weekly_cap_h": None, "monthly_cap_h": None,
                        "today_h": 0.0, "wtd": {"actual_h": 3.0},
                        "7d": {"actual_h": 3.0}, "30d": {"actual_h": 12.0}},
         }}
    rows = [(k, n, d) for k, n, _, d in fc.iter_rows(s)]
    assert rows == [("group", "Billable", 0), ("group", "Sub", 1),
                    ("engagement", "ClientA", 2), ("engagement", "ClientB", 1)], rows


def test_iter_rows_wildcard_style_empty_direct_renders_flat():
    # A group with no direct_engagements (e.g. a wildcard '*' roll-up, or the
    # synthesized legacy total_budget 'Billable') claims nothing — engagements
    # keep the flat pre-#66 tail.
    s = {"groups": [
            {"name": "Billable", "depth": 0, "weekly_cap_h": 20, "monthly_cap_h": 80,
             "today_h": 0.0, "wtd": {"actual_h": 5.0, "hours_left": 15.0, "over": False},
             "7d": {"actual_h": 5.0}, "30d": {"actual_h": 20.0},
             "direct_engagements": []},
         ],
         "engagements": {
            "ClientA": {"track_only": True, "weekly_cap_h": None, "monthly_cap_h": None,
                        "today_h": 0.0, "wtd": {"actual_h": 2.0},
                        "7d": {"actual_h": 2.0}, "30d": {"actual_h": 8.0}},
         }}
    rows = [(k, n, d) for k, n, _, d in fc.iter_rows(s)]
    assert rows == [("group", "Billable", 0), ("engagement", "ClientA", 0)], rows
