import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pulse_issue  # noqa: E402

CONFIG = {
    "account": "davidmshaner",
    "repo": "davidmshaner/shorty",
    "project_owner": "davidmshaner",
    "board_number": 5,
    "status_field": "Status",
    "status_value": "Backlog",
}

AUTH = (
    "github.com\n"
    "  Logged in to github.com account davidmshaner (keyring)\n"
    "  - Active account: false\n"
    "  - Token scopes: 'gist', 'project', 'read:org', 'repo', 'workflow'\n"
    "\n"
    "  Logged in to github.com account shanerconsulting (keyring)\n"
    "  - Active account: true\n"
    "  - Token scopes: 'gist', 'read:org', 'repo'\n"
)
AUTH_NO_PROJECT = (
    "github.com\n"
    "  Logged in to github.com account davidmshaner (keyring)\n"
    "  - Active account: true\n"
    "  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'\n"
)

FIELD_LIST = {
    "fields": [
        {"id": "PVTF_status", "name": "Status", "type": "ProjectV2SingleSelectField",
         "options": [
             {"id": "opt_backlog", "name": "Backlog"},
             {"id": "opt_inprog", "name": "In Progress"},
             {"id": "opt_done", "name": "Done"},
         ]},
    ]
}
ITEM_LIST = {
    "items": [
        {"id": "PVTI_existing", "content": {"type": "Issue", "number": 42, "title": "On board"}},
    ]
}

FULL_FIELDS = {
    "title": "Toast clips on second monitor",
    "labels": ["bug"],
    "origin": "david",
    "body": {
        "intent": "Fix the mastery toast clipping when iTerm is on an external display.",
        "context": "Repro: dock iTerm to the 2nd monitor, master a shortcut — card is cut off.",
        "relevant_code": ["Sources/Shorty/ToastWindow.swift:50 — panel origin uses NSScreen.main"],
        "acceptance": ["toast renders fully on the active screen", "no regression on the built-in display"],
        "approach": "Anchor to the screen containing iTerm, not NSScreen.main.",
        "watchouts": {"gotcha": "none matched", "spec": "none found", "slice": "Slice 2 (toasts)"},
    },
}
SPARSE_FIELDS = {
    "title": "Tidy README",
    "labels": ["chore"],
    "origin": "agent",
    "body": {"intent": "Tidy the README.", "context": "", "relevant_code": [],
             "acceptance": [], "approach": None, "watchouts": {}},
}


def test_parse_active_account():
    assert pulse_issue.parse_active_account(AUTH) == "shanerconsulting"


def test_account_has_scope_true():
    assert pulse_issue.account_has_scope(AUTH, "davidmshaner", "project") is True


def test_account_has_scope_false_missing():
    assert pulse_issue.account_has_scope(AUTH, "shanerconsulting", "project") is False


def test_resolve_account_switches_to_davidmshaner_when_scoped():
    acct, need_switch, restore = pulse_issue.resolve_issuing_account(AUTH, "shanerconsulting", "davidmshaner")
    assert acct == "davidmshaner"
    assert need_switch is True
    assert restore == "shanerconsulting"


def test_resolve_account_none_when_underscoped():
    acct, _, _ = pulse_issue.resolve_issuing_account(AUTH_NO_PROJECT, "davidmshaner", "davidmshaner")
    # davidmshaner here lacks 'project' -> cannot place on board
    assert acct is None


def test_render_body_has_all_sections():
    out = pulse_issue.render_issue_body(FULL_FIELDS)
    for h in ["## Intent", "## Context", "## Relevant code", "## Acceptance criteria",
              "## Suggested approach", "## Watch-outs", "## Meta"]:
        assert h in out


def test_render_body_acceptance_checkboxes():
    out = pulse_issue.render_issue_body(FULL_FIELDS)
    assert "- [ ] toast renders fully on the active screen" in out


def test_render_body_empty_sections_say_none():
    out = pulse_issue.render_issue_body(SPARSE_FIELDS)
    assert "_none provided_" in out
    assert "_none found_" in out
    assert "- [ ] _to be defined_" in out
    assert "_none; worker's discretion_" in out


def test_render_body_meta_has_label_and_origin():
    out = pulse_issue.render_issue_body(FULL_FIELDS)
    assert "bug" in out and "david" in out and "Backlog" in out


def test_render_body_no_em_dash_in_skeleton():
    out = pulse_issue.render_issue_body(SPARSE_FIELDS).replace(SPARSE_FIELDS["body"]["intent"], "")
    assert "—" not in out


def test_build_create_argv_uses_explicit_repo():
    argv = pulse_issue.build_create_argv("davidmshaner/shorty", "T", "/tmp/b.md", ["bug"])
    assert argv[:3] == ["gh", "issue", "create"]
    assert "--repo" in argv and "davidmshaner/shorty" in argv
    assert "--body-file" in argv and "/tmp/b.md" in argv


def test_build_create_argv_multiple_labels():
    argv = pulse_issue.build_create_argv("davidmshaner/shorty", "T", "/tmp/b.md", ["bug", "tech-debt"])
    assert argv.count("--label") == 2


def test_find_status_option_backlog():
    fid, oid = pulse_issue.find_status_option(FIELD_LIST, "Status", "Backlog")
    assert fid == "PVTF_status" and oid == "opt_backlog"


def test_find_status_option_missing():
    fid, oid = pulse_issue.find_status_option(FIELD_LIST, "Status", "Nope")
    assert fid == "PVTF_status" and oid is None


def test_issue_is_on_board_found():
    assert pulse_issue.issue_is_on_board(ITEM_LIST, 42) == "PVTI_existing"


def test_issue_is_on_board_not_found():
    assert pulse_issue.issue_is_on_board(ITEM_LIST, 99) is None


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, argv, text=True, capture_output=True):
        self.calls.append(argv)
        joined = " ".join(argv)
        for match, stdout, rc in self.responses:
            if match in joined:
                r = type("R", (), {})(); r.stdout = stdout; r.stderr = ""; r.returncode = rc
                return r
        r = type("R", (), {})(); r.stdout = ""; r.stderr = ""; r.returncode = 0
        return r


def _fields_file(tmp_path, fields=FULL_FIELDS):
    p = tmp_path / "fields.json"; p.write_text(json.dumps(fields)); return str(p)


def test_main_dry_run_does_not_create(tmp_path, capsys):
    runner = FakeRunner([("auth status", AUTH, 0)])
    rc = pulse_issue.main(["--fields", _fields_file(tmp_path), "--dry-run"], config=CONFIG, runner=runner)
    out = capsys.readouterr().out
    assert rc == 0
    assert "gh issue create" in out
    assert not any("issue create" in " ".join(c) for c in runner.calls)


def test_main_creates_switches_and_places(tmp_path, capsys):
    runner = FakeRunner([
        ("auth status", AUTH, 0),
        ("issue create", "https://github.com/davidmshaner/shorty/issues/12\n", 0),
        ("project item-list", json.dumps(ITEM_LIST), 0),
        ("project view", json.dumps({"id": "PVT_proj"}), 0),
        ("project item-add", json.dumps({"id": "PVTI_new"}), 0),
        ("project field-list", json.dumps(FIELD_LIST), 0),
        ("project item-edit", "", 0),
    ])
    rc = pulse_issue.main(["--fields", _fields_file(tmp_path)], config=CONFIG, runner=runner)
    calls = [" ".join(c) for c in runner.calls]
    assert rc == 0
    assert any("auth switch --user davidmshaner" in c for c in calls)
    assert any("auth switch --user shanerconsulting" in c for c in calls[-2:])  # restored
    assert any("issue create" in c for c in calls)


def test_main_missing_project_scope_blocks(tmp_path, capsys):
    runner = FakeRunner([("auth status", AUTH_NO_PROJECT, 0)])
    rc = pulse_issue.main(["--fields", _fields_file(tmp_path)], config=CONFIG, runner=runner)
    out = capsys.readouterr().out
    assert rc != 0
    assert "gh auth refresh -s project --user davidmshaner" in out
    assert not any("issue create" in " ".join(c) for c in runner.calls)


def test_main_parses_url_with_trailing_line(tmp_path, capsys):
    runner = FakeRunner([
        ("auth status", AUTH, 0),
        ("issue create",
         "https://github.com/davidmshaner/shorty/issues/13\n! upgrade gh\n", 0),
        ("project item-list", json.dumps(ITEM_LIST), 0),
        ("project view", json.dumps({"id": "PVT_proj"}), 0),
        ("project item-add", json.dumps({"id": "PVTI_new"}), 0),
        ("project field-list", json.dumps(FIELD_LIST), 0),
        ("project item-edit", "", 0),
    ])
    rc = pulse_issue.main(["--fields", _fields_file(tmp_path)], config=CONFIG, runner=runner)
    out = capsys.readouterr().out
    assert rc == 0 and "issues/13" in out
