#!/usr/bin/env python3
"""test_nested_groups.py — nested group hierarchy (#31).

A group's `members` may name OTHER groups as well as engagements (recursive,
no new field). These pure helpers resolve a group to its transitive engagement
set, order the group forest for rendering, and validate the config loudly
(unknown member / cycle / ancestor-descendant double-count / registry child
subpath) so a bad edit fails instead of silently miscounting.

Bucket/group names here are generic labels (GroupA, ClientA, ProjectX...).

Run: python3 tests/test_nested_groups.py
"""
from __future__ import annotations

import sys
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent / "src" / "pulse"
sys.path.insert(0, str(WIDGET))

from snapshot import (  # noqa: E402
    appetite_errors,
    build_group_block,
    group_tree_order,
    registry_child_path_errors,
    resolve_group_engagements,
)


def _est():
    """A small engagement_state: leaf engagements with per-window hours."""
    def e(today, wtd, d7, d30):
        return {"today_h": today, "wtd": {"actual_h": wtd},
                "7d": {"actual_h": d7}, "30d": {"actual_h": d30}, "bucket": "x"}
    return {
        "ClientA": e(1.0, 10.0, 11.0, 40.0),
        "ClientB": e(2.0, 8.0, 9.0, 30.0),
        "ProjectX": e(0.5, 3.0, 3.5, 12.0),
        "ProjectY": e(0.0, 1.0, 1.0, 4.0),
    }


# --- recursive member resolution -------------------------------------------

ENGS = ["ClientA", "ClientB", "ClientC", "ProjectX", "ProjectY", "Leftover"]


def test_resolve_flat_group_is_its_engagements():
    gbn = {"Billable": ["ClientA", "ClientB"]}
    assert resolve_group_engagements("Billable", gbn, ENGS) == ["ClientA", "ClientB"]


def test_resolve_nested_group_expands_subgroups_in_order():
    gbn = {
        "Billable": ["ClientA", "ClientB", "ClientC"],
        "Personal Software": ["ProjectX", "ProjectY"],
        "All Work": ["Billable", "Personal Software", "Leftover"],
    }
    assert resolve_group_engagements("All Work", gbn, ENGS) == [
        "ClientA", "ClientB", "ClientC", "ProjectX", "ProjectY", "Leftover",
    ]


def test_resolve_dedupes_engagement_reachable_twice():
    # ClientA reachable directly AND via Billable — resolved set counts it once
    # (the summed rollup must never double-count).
    gbn = {"Billable": ["ClientA", "ClientB"], "All Work": ["Billable", "ClientA"]}
    assert resolve_group_engagements("All Work", gbn, ENGS) == ["ClientA", "ClientB"]


def test_resolve_wildcard_is_all_engagements():
    gbn = {"All Work": "*"}
    assert resolve_group_engagements("All Work", gbn, ENGS) == ENGS


def test_resolve_skips_unknown_members():
    gbn = {"G": ["ClientA", "Ghost"]}
    assert resolve_group_engagements("G", gbn, ENGS) == ["ClientA"]


def test_resolve_is_cycle_safe():
    # A <-> B cycle must terminate (validation rejects it, but resolve must not hang).
    gbn = {"A": ["B", "ClientA"], "B": ["A", "ClientB"]}
    out = resolve_group_engagements("A", gbn, ENGS)
    assert "ClientA" in out and "ClientB" in out


# --- forest ordering + depth (drives indented rendering) --------------------

def test_tree_order_flat_is_definition_order_all_depth0():
    groups = [
        {"name": "Billable", "members": ["ClientA", "ClientB"]},
        {"name": "All Work", "members": ["ClientA", "ClientB", "ClientC"]},
    ]
    assert group_tree_order(groups) == [("Billable", 0), ("All Work", 0)]


def test_tree_order_nested_is_preorder_with_depth():
    groups = [
        {"name": "Billable", "members": ["ClientA", "ClientB"]},
        {"name": "Personal Software", "members": ["ProjectX"]},
        {"name": "All Work", "members": ["Billable", "Personal Software", "Leftover"]},
    ]
    # A referenced sub-group is rendered only under its parent, not at top level.
    assert group_tree_order(groups) == [
        ("All Work", 0), ("Billable", 1), ("Personal Software", 1),
    ]


def test_tree_order_wildcard_group_is_a_root_depth0():
    groups = [{"name": "All Work", "members": "*"}]
    assert group_tree_order(groups) == [("All Work", 0)]


# --- nested rollup math (no double-counting) --------------------------------

def test_block_sum_is_over_resolved_engagements():
    est = _est()
    present = ["ClientA", "ClientB"]        # a flat "Billable" group
    blk = build_group_block("Billable", present, est, 20.0, 80.0, depth=0)
    assert blk["today_h"] == 3.0            # 1.0 + 2.0
    assert blk["wtd"]["actual_h"] == 18.0   # 10 + 8
    assert blk["30d"]["actual_h"] == 70.0   # 40 + 30
    assert blk["weekly_cap_h"] == 20.0 and blk["depth"] == 0


def test_nested_group_rolls_up_leaves_once():
    # All Work = Billable(ClientA,ClientB) + Personal Software(ProjectX,ProjectY).
    # Its rollup is the sum of the four distinct leaves — each counted once.
    est = _est()
    present = resolve_group_engagements(
        "All Work",
        {"Billable": ["ClientA", "ClientB"],
         "Personal Software": ["ProjectX", "ProjectY"],
         "All Work": ["Billable", "Personal Software"]},
        list(est.keys()),
    )
    blk = build_group_block("All Work", present, est, 40.0, 160.0, depth=0)
    assert blk["wtd"]["actual_h"] == 22.0   # 10 + 8 + 3 + 1, no double count
    assert blk["30d"]["actual_h"] == 86.0   # 40 + 30 + 12 + 4


def test_capless_group_block_is_track_style():
    est = _est()
    blk = build_group_block("Personal Software", ["ProjectX", "ProjectY"], est,
                            None, None, depth=1)
    assert blk["weekly_cap_h"] is None and blk["monthly_cap_h"] is None
    assert blk["track_only"] is True
    assert blk["wtd"]["actual_h"] == 4.0
    assert "over" not in blk["wtd"]         # no cap -> no over/left verdict
    assert blk["depth"] == 1


# --- validation: unknown member --------------------------------------------

def test_validate_unknown_member_flagged():
    errs = appetite_errors({"ClientA": {"weekly_hours": 8}},
                           groups={"G": ["ClientA", "Ghost"]})
    assert len(errs) == 1 and "Ghost" in errs[0] and "G" in errs[0]


def test_validate_group_member_is_allowed():
    # a member naming another group is valid, not "unknown"
    errs = appetite_errors({"ClientA": {"weekly_hours": 8}},
                           groups={"Billable": ["ClientA"], "All Work": ["Billable"]})
    assert errs == []


# --- validation: cycles -----------------------------------------------------

def test_validate_cycle_flagged():
    errs = appetite_errors({"ClientA": {"weekly_hours": 8}},
                           groups={"A": ["B"], "B": ["A"]})
    assert any("cycle" in e.lower() for e in errs)


def test_validate_self_reference_is_a_cycle():
    errs = appetite_errors({}, groups={"A": ["A"]})
    assert any("cycle" in e.lower() for e in errs)


# --- validation: ancestor/descendant double-count --------------------------

def test_validate_diamond_double_count_flagged():
    # ClientA reachable via Billable AND directly under All Work -> its rollup
    # would count ClientA twice. Loud error, never a silent miscount.
    errs = appetite_errors({"ClientA": {}, "ClientB": {}},
                           groups={"Billable": ["ClientA", "ClientB"],
                                   "All Work": ["Billable", "ClientA"]})
    assert any("more than once" in e or "double" in e.lower() for e in errs)
    assert any("ClientA" in e for e in errs)


def test_validate_clean_nested_config_passes():
    errs = appetite_errors(
        {"ClientA": {"weekly_hours": 8}, "ClientB": {"weekly_hours": 6},
         "ProjectX": {}, "Leftover": {}},
        groups={"Billable": ["ClientA", "ClientB"],
                "Personal Software": ["ProjectX"],
                "All Work": ["Billable", "Personal Software", "Leftover"]},
    )
    assert errs == []


# --- validation: registry child source_path subpath ------------------------

def test_registry_child_under_parent_ok():
    buckets = [{"name": "Personal", "source_path": "/Users/x/personal",
                "children": [{"name": "PulseWork", "source_path": "/Users/x/personal/pulse"}]}]
    assert registry_child_path_errors(buckets) == []


def test_registry_child_not_under_parent_flagged():
    buckets = [{"name": "Personal", "source_path": "/Users/x/personal",
                "children": [{"name": "Stray", "source_path": "/Users/x/work/stray"}]}]
    errs = registry_child_path_errors(buckets)
    assert len(errs) == 1 and "Stray" in errs[0] and "Personal" in errs[0]


def test_registry_child_path_check_recurses_to_grandchildren():
    buckets = [{"name": "Root", "source_path": "/a",
                "children": [{"name": "Child", "source_path": "/a/b",
                              "children": [{"name": "Bad", "source_path": "/c/d"}]}]}]
    errs = registry_child_path_errors(buckets)
    assert len(errs) == 1 and "Bad" in errs[0]


def test_appetite_errors_folds_in_registry_check():
    buckets = [{"name": "P", "source_path": "/a",
                "children": [{"name": "Bad", "source_path": "/z"}]}]
    errs = appetite_errors({"ClientA": {}}, groups={"G": ["ClientA"]},
                           registry_buckets=buckets)
    assert any("Bad" in e for e in errs)


# --- shipped examples must validate clean -----------------------------------

def test_shipped_example_configs_validate_clean():
    import yaml
    root = Path(__file__).resolve().parent.parent
    ap = yaml.safe_load((root / "examples" / "appetite.example.yaml").read_text())
    reg = yaml.safe_load((root / "examples" / "bucket-registry.example.yaml").read_text())
    engs = ap.get("engagements", {})
    grps = {n: (g or {}).get("members") for n, g in (ap.get("groups") or {}).items()}
    assert appetite_errors(engs, groups=grps,
                           registry_buckets=reg.get("buckets")) == []


# --- back-compat: single-arg call (income-mode call sites) ------------------

def test_appetite_errors_single_arg_still_works():
    # existing callers pass only the engagements dict; groups/registry default off
    assert appetite_errors({"ClientA": {"weekly_hours": 8}}) == []
    assert len(appetite_errors({"Bad": {"bill_rate": 200, "weekly_hours": 8}})) == 1


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
