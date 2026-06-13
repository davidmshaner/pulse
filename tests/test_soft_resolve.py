import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src' / 'pulse'))
from snapshot import soft_resolve_meeting

LEARN = {
    "patterns": {
        "lead@globex.com": ["SC", "Globex"],
        "ceo@acme.com": ["SC", "Acme"],
        "dev@initech.com": ["SC", "Acme", "Initech"],
    },
    "domain_patterns": {"initech.com": ["SC", "Acme", "Initech"]},
    "title_rules": {"standup": ["SC", "Internal"]},
    "multi_bucket_attendees": {"partner@multi.com": [["Alpha"], ["SC", "Beta"]]},
}


def test_title_rule_beats_attendee():
    m = {"title": "Weekly Standup", "co_attendees": ["lead@globex.com"]}
    assert soft_resolve_meeting(m, LEARN) == ["SC", "Internal"]

def test_exact_pattern():
    m = {"title": "Globex sync", "co_attendees": ["lead@globex.com"]}
    assert soft_resolve_meeting(m, LEARN) == ["SC", "Globex"]

def test_domain_fallback():
    m = {"title": "intro", "co_attendees": ["newhire@initech.com"]}
    assert soft_resolve_meeting(m, LEARN) == ["SC", "Acme", "Initech"]

def test_nested_tiebreak_deepest_wins():
    m = {"title": "install", "co_attendees": ["ceo@acme.com", "dev@initech.com"]}
    assert soft_resolve_meeting(m, LEARN) == ["SC", "Acme", "Initech"]

def test_conflicting_non_nested_stays_unresolved():
    m = {"title": "x", "co_attendees": ["lead@globex.com", "ceo@acme.com"]}
    assert soft_resolve_meeting(m, LEARN) is None   # [SC,Globex] vs [SC,Acme] not nested

def test_multi_bucket_attendee_does_not_vote():
    # partner is explicitly ambiguous → skipped; ceo carries it to Acme
    m = {"title": "weekly", "co_attendees": ["partner@multi.com", "ceo@acme.com"]}
    assert soft_resolve_meeting(m, LEARN) == ["SC", "Acme"]

def test_unknown_attendee_unresolved():
    m = {"title": "x", "co_attendees": ["nobody@unknown.com"]}
    assert soft_resolve_meeting(m, LEARN) is None
