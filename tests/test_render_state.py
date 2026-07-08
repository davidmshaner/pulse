import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src' / 'pulse'))
from panel.render_state import build_view_model

STATE = {
    "generated_at": "2026-06-12T11:25:00-04:00",
    "groups": [
        {"name": "Billable", "weekly_cap_h": 32.0, "monthly_cap_h": 128.0, "today_h": 4.56,
         "wtd": {"actual_h": 34.88, "hours_over": 2.9, "over": True},
         "7d":  {"actual_h": 35.41, "hours_over": 3.4, "over": True},
         "30d": {"actual_h": 165.67, "hours_over": 37.7, "over": True}},
        {"name": "All Work", "weekly_cap_h": 40.0, "monthly_cap_h": 200.0, "today_h": 6.0,
         "wtd": {"actual_h": 39.88, "hours_left": 0.1, "over": False},
         "7d":  {"actual_h": 41.0, "hours_over": 1.0, "over": True},
         "30d": {"actual_h": 185.0, "hours_left": 15.0, "over": False}},
    ],
    "engagements": {
        "Acme": {"track_only": False, "weekly_cap_h": 12.8, "monthly_cap_h": 56.0,
                 "today_h": 2.4, "meeting_h": 3.2,
                 "wtd": {"actual_h": 24.5, "hours_over": 11.7, "over": True},
                 "7d":  {"actual_h": 26.0, "hours_over": 13.2, "over": True},
                 "30d": {"actual_h": 94.0, "hours_over": 38.0, "over": True}},
        "Globex": {"track_only": False, "weekly_cap_h": 1.1, "monthly_cap_h": 5.0, "today_h": 0.0,
                   "wtd": {"actual_h": 0.0, "hours_left": 1.1, "over": False},
                   "7d":  {"actual_h": 0.3, "hours_left": 0.8, "over": False},
                   "30d": {"actual_h": 16.0, "hours_over": 11.0, "over": True}},
        "Personal": {"track_only": True, "weekly_cap_h": None, "monthly_cap_h": None, "today_h": 1.0,
                     "wtd": {"actual_h": 5.0}, "7d": {"actual_h": 6.0}, "30d": {"actual_h": 20.0}},
    },
    "live_bucket": {"bucket_path": ["Consulting", "Acme"], "elapsed_min": 4},
    "needs_llm": {"sessions": 3, "meetings": 11},
    "meetings_wtd": 6,
    "people": [{"name": "Dana", "project": "Acme"}, {"name": "Wei", "project": "Globex"}],
    "uncategorized_detail": {"sessions": ["api.py"], "meetings": ["Acme sync"]},
    "overhead_sessions": 5,
    "repo_path": "/Users/x/dev/pulse",
}


def test_groups_emitted_with_week_and_month():
    vm = build_view_model(STATE)
    names = [g["name"] for g in vm["groups"]]
    assert names == ["Billable", "All Work"]            # definition order preserved
    bill = vm["groups"][0]
    assert bill["is_group"] is True
    assert bill["week"]["actual_h"] == 34.9 and bill["week"]["cap_h"] == 32.0
    assert bill["week"]["pct"] == 109 and bill["week"]["status"] == "over"
    assert bill["month"]["actual_h"] == 165.7 and bill["month"]["cap_h"] == 128.0
    assert bill["month"]["pct"] == 129 and bill["month"]["status"] == "over"


def test_engagements_sorted_capped_over_then_under_then_trackonly():
    vm = build_view_model(STATE)
    names = [e["name"] for e in vm["engagements"]]
    assert names == ["Acme", "Globex", "Personal"]      # over, under, then track-only
    acme = vm["engagements"][0]
    assert acme["week"]["pct"] == 191 and acme["week"]["status"] == "over"
    assert acme["month"]["actual_h"] == 94.0 and acme["month"]["cap_h"] == 56.0
    assert acme["today_h"] == 2.4 and acme["d7_h"] == 26.0


def test_row_carries_day_block_track_style():
    # A day has no cap, so every row's `day` block is cap-less (track style),
    # mirroring today_h — regardless of whether the row is capped for the week.
    vm = build_view_model(STATE)
    acme = [e for e in vm["engagements"] if e["name"] == "Acme"][0]
    assert acme["day"]["actual_h"] == 2.4
    assert acme["day"]["cap_h"] is None
    assert acme["day"]["status"] == "track"
    assert acme["day"]["pct"] == 0


def test_group_carries_day_block():
    vm = build_view_model(STATE)
    bill = vm["groups"][0]
    assert bill["day"]["actual_h"] == 4.6            # round(4.56, 1)
    assert bill["day"]["cap_h"] is None
    assert bill["day"]["status"] == "track"


def test_day_block_matches_today_h_everywhere():
    vm = build_view_model(STATE)
    for e in vm["engagements"] + vm["groups"]:
        assert e["day"]["actual_h"] == e["today_h"], e["name"]


def test_track_only_row_has_no_cap():
    vm = build_view_model(STATE)
    p = [e for e in vm["engagements"] if e["name"] == "Personal"][0]
    assert p["track_only"] is True
    assert p["week"]["cap_h"] is None and p["week"]["status"] == "track"
    assert p["week"]["actual_h"] == 5.0 and p["month"]["actual_h"] == 20.0


def test_meeting_hours_surfaced_per_engagement():
    vm = build_view_model(STATE)
    acme = [e for e in vm["engagements"] if e["name"] == "Acme"][0]
    assert acme["meeting_h"] == 3.2
    globex = [e for e in vm["engagements"] if e["name"] == "Globex"][0]
    assert globex["meeting_h"] == 0.0


def test_legacy_total_back_compat():
    legacy = {"total": {"weekly_cap_h": 32.0, "monthly_cap_h": 128.0, "today_h": 1.0,
                        "wtd": {"actual_h": 10.0, "hours_left": 22.0, "over": False},
                        "7d": {"actual_h": 10.0}, "30d": {"actual_h": 40.0}},
              "engagements": {}}
    vm = build_view_model(legacy)
    assert [g["name"] for g in vm["groups"]] == ["Billable"]
    assert vm["groups"][0]["week"]["cap_h"] == 32.0


def test_now_footer():
    vm = build_view_model(STATE)
    assert vm["now"] == {"label": "Consulting · Acme", "elapsed_min": 4}


def test_now_footer_absent_when_no_live_bucket():
    s = dict(STATE); s["live_bucket"] = None
    assert build_view_model(s)["now"] is None


def test_uncategorized_passthrough():
    vm = build_view_model(STATE)
    assert vm["uncategorized"] == {"sessions": 3, "meetings": 11}


def test_people_and_meeting_count_passthrough():
    vm = build_view_model(STATE)
    assert vm["meetings_wtd"] == 6
    assert vm["people"] == [{"name": "Dana", "project": "Acme"},
                            {"name": "Wei", "project": "Globex"}]


def test_repo_path_passthrough():
    assert build_view_model(STATE)["repo_path"] == "/Users/x/dev/pulse"
    assert build_view_model({})["repo_path"] == ""


def test_overhead_and_uncategorized_detail_defaults():
    assert build_view_model({})["overhead_sessions"] == 0
    assert build_view_model({})["uncategorized_detail"] == {"sessions": [], "meetings": []}


# --- update banner (issue #25) --------------------------------------------

def test_update_absent_when_no_update_check_key():
    # Old state.json (pre-#25) has no update_check block — must render fine, no banner.
    assert build_view_model(STATE)["update"] is None
    assert build_view_model({})["update"] is None


def test_update_absent_when_current():
    s = dict(STATE)
    s["update_check"] = {"behind": False, "local_head": "a" * 40, "remote_head": "a" * 40}
    assert build_view_model(s)["update"] is None


def test_update_banner_when_behind_carries_command_with_repo_path():
    s = dict(STATE)
    s["update_check"] = {"behind": True, "local_head": "a" * 40, "remote_head": "b" * 40}
    up = build_view_model(s)["update"]
    assert up is not None
    # the exact one-line update command, scoped to the user's clone
    assert up["command"] == "cd /Users/x/dev/pulse && git pull && bash install-mac.sh"


def test_update_command_without_repo_path():
    s = {"update_check": {"behind": True}}
    up = build_view_model(s)["update"]
    assert up["command"] == "git pull && bash install-mac.sh"
