import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from panel.render_state import build_view_model

STATE = {
    "generated_at": "2026-06-12T11:25:00-04:00",
    "total": {
        "weekly_cap_h": 32.0, "monthly_cap_h": 128.0, "today_h": 4.56,
        "wtd": {"actual_h": 34.88, "hours_over": 2.9, "over": True},
        "7d":  {"actual_h": 35.41, "hours_over": 3.4, "over": True},
        "30d": {"actual_h": 165.67, "hours_over": 37.7, "over": True},
    },
    "engagements": {
        "Acme": {"weekly_cap_h": 12.8, "monthly_cap_h": 56.0, "today_h": 2.4,
                 "meeting_h": 3.2,
                 "wtd": {"actual_h": 24.5, "hours_over": 11.7, "over": True},
                 "7d":  {"actual_h": 26.0, "hours_over": 13.2, "over": True},
                 "30d": {"actual_h": 94.0, "hours_over": 38.0, "over": True}},
        "Globex": {"weekly_cap_h": 1.1, "monthly_cap_h": 5.0, "today_h": 0.0,
                   "wtd": {"actual_h": 0.0, "hours_left": 1.1, "over": False},
                   "7d":  {"actual_h": 0.3, "hours_left": 0.8, "over": False},
                   "30d": {"actual_h": 16.0, "hours_over": 11.0, "over": True}},
    },
    "live_bucket": {"bucket_path": ["Consulting", "Acme"], "elapsed_min": 4},
    "needs_llm": {"sessions": 3, "meetings": 11},
    "meetings_wtd": 6,
    "people": [{"name": "Dana", "project": "Acme"}, {"name": "Wei", "project": "Globex"}],
    "uncategorized_detail": {"sessions": ["api.py"], "meetings": ["Acme sync"]},
}

def test_total_block_normalized():
    vm = build_view_model(STATE)
    assert vm["total"]["actual_h"] == 34.9          # rounded to 1dp
    assert vm["total"]["cap_h"] == 32.0
    assert vm["total"]["status"] == "over"
    assert vm["total"]["pct"] == 109                # round(34.88/32*100)

def test_engagements_sorted_over_first_then_name():
    vm = build_view_model(STATE)
    names = [e["name"] for e in vm["engagements"]]
    assert names == ["Acme", "Globex"]              # over-budget first, then alpha
    acme = vm["engagements"][0]
    assert acme["status"] == "over" and acme["pct"] == 191
    assert acme["today_h"] == 2.4 and acme["d7_h"] == 26.0
    assert acme["d30_actual"] == 94.0 and acme["d30_cap"] == 56.0

def test_status_thresholds():
    vm = build_view_model(STATE)
    globex = [e for e in vm["engagements"] if e["name"] == "Globex"][0]
    assert globex["status"] == "under"              # wtd 0/1.1 = 0%

def test_now_footer():
    vm = build_view_model(STATE)
    assert vm["now"] == {"label": "Consulting · Acme", "elapsed_min": 4}

def test_now_footer_absent_when_no_live_bucket():
    s = dict(STATE); s["live_bucket"] = None
    vm = build_view_model(s)
    assert vm["now"] is None

def test_uncategorized_passthrough():
    vm = build_view_model(STATE)
    assert vm["uncategorized"] == {"sessions": 3, "meetings": 11}

def test_meeting_hours_surfaced_per_engagement():
    vm = build_view_model(STATE)
    acme = [e for e in vm["engagements"] if e["name"] == "Acme"][0]
    assert acme["meeting_h"] == 3.2
    globex = [e for e in vm["engagements"] if e["name"] == "Globex"][0]
    assert globex["meeting_h"] == 0.0          # missing meeting_h defaults to 0

def test_people_and_meeting_count_passthrough():
    vm = build_view_model(STATE)
    assert vm["meetings_wtd"] == 6
    assert vm["people"] == [{"name": "Dana", "project": "Acme"},
                            {"name": "Wei", "project": "Globex"}]

def test_uncategorized_detail_passthrough_and_default():
    vm = build_view_model(STATE)
    assert vm["uncategorized_detail"] == {"sessions": ["api.py"], "meetings": ["Acme sync"]}
    s = dict(STATE); del s["uncategorized_detail"]
    assert build_view_model(s)["uncategorized_detail"] == {"sessions": [], "meetings": []}
