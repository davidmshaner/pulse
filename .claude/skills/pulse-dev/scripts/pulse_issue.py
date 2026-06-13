"""pulse_issue.py — deterministic GitHub-issue intake for the /pulse-dev skill (issue mode).

Single repo (shanerconsulting/pulse), single account (shanerconsulting). Stdlib only.
Trimmed from GI's gi_issue.py: keeps gh-account choreography, the standardized body
contract, issue creation, and idempotent Projects-v2 board placement. The model-driven
work (capture, enrichment, dedup, classification) lives in SKILL.md.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _account_blocks(auth_status_text: str) -> dict:
    blocks, current, buf = {}, None, []
    for line in auth_status_text.splitlines():
        m = re.search(r"Logged in to github\.com account (\S+)", line)
        if m:
            if current is not None:
                blocks[current] = "\n".join(buf)
            current, buf = m.group(1), [line]
        elif current is not None:
            buf.append(line)
    if current is not None:
        blocks[current] = "\n".join(buf)
    return blocks


def parse_active_account(auth_status_text: str):
    for acct, block in _account_blocks(auth_status_text).items():
        if "Active account: true" in block:
            return acct
    return None


def account_has_scope(auth_status_text: str, account: str, scope: str) -> bool:
    block = _account_blocks(auth_status_text).get(account, "")
    m = re.search(r"Token scopes:\s*(.+)", block)
    if not m:
        return False
    tokens = [t for t in re.split(r"[',\s]+", m.group(1)) if t]
    return scope in tokens


def resolve_issuing_account(auth_status_text: str, active_account, target_account: str,
                            required_scopes=("repo", "project")):
    """Use the mapped target account if authed + scoped (switch to it if needed); else
    fall back to the active account when IT carries the scopes (portable). Returns
    (account_or_None, need_switch, restore_to)."""
    blocks = _account_blocks(auth_status_text)

    def has_all(acct):
        return bool(acct) and acct in blocks and all(
            account_has_scope(auth_status_text, acct, s) for s in required_scopes)

    if target_account in blocks:
        if not has_all(target_account):
            return (None, False, active_account)
        return (target_account, active_account != target_account, active_account)
    if has_all(active_account):
        return (active_account, False, active_account)
    return (None, False, active_account)


def _bullets(items, empty):
    return "\n".join(f"- {it}" for it in items) if items else empty


def render_issue_body(fields: dict) -> str:
    b = fields.get("body", {})
    intent = (b.get("intent") or "").strip() or "_not specified_"
    context = (b.get("context") or "").strip() or "_none provided_"
    relevant = _bullets(b.get("relevant_code") or [], "_none found_")
    acc = b.get("acceptance") or []
    acceptance = "\n".join(f"- [ ] {a}" for a in acc) if acc else "- [ ] _to be defined_"
    approach = (b.get("approach") or "").strip() or "_none; worker's discretion_"
    w = b.get("watchouts") or {}
    watch = "\n".join([
        f"- Gotcha: {w.get('gotcha') or '_none matched_'}",
        f"- Related spec: {w.get('spec') or '_none found_'}",
        f"- Slice: {w.get('slice') or '_n/a_'}",
    ])
    labels = ", ".join(fields.get("labels", [])) or "?"
    meta_line = " | ".join([
        f"Repo: {fields.get('meta', {}).get('repo', 'shanerconsulting/pulse')}",
        f"Label: {labels}",
        f"Origin: {fields.get('origin', 'david')}",
        f"Column: {fields.get('meta', {}).get('column', 'Backlog')}",
    ])
    return (
        f"## Intent\n{intent}\n\n"
        f"## Context\n{context}\n\n"
        f"## Relevant code\n{relevant}\n\n"
        f"## Acceptance criteria\n{acceptance}\n\n"
        f"## Suggested approach\n{approach}\n\n"
        f"## Watch-outs\n{watch}\n\n"
        f"## Meta\n{meta_line}\n"
    )


def build_create_argv(repo_full: str, title: str, body_file: str, labels) -> list:
    argv = ["gh", "issue", "create", "--repo", repo_full, "--title", title, "--body-file", body_file]
    for lb in labels:
        argv += ["--label", lb]
    return argv


def find_status_option(field_list_json: dict, field_name: str, option_name: str):
    for field in field_list_json.get("fields", []):
        if field.get("name") == field_name:
            for opt in field.get("options", []):
                if opt.get("name") == option_name:
                    return (field.get("id"), opt.get("id"))
            return (field.get("id"), None)
    return (None, None)


def issue_is_on_board(item_list_json: dict, issue_number: int):
    for item in item_list_json.get("items", []):
        if item.get("content", {}).get("number") == issue_number:
            return item.get("id")
    return None


def _gh(runner, argv):
    return runner(argv, text=True, capture_output=True)


def main(argv, config=None, runner=None) -> int:
    if runner is None:
        runner = lambda a, text=True, capture_output=True: subprocess.run(
            a, text=text, capture_output=capture_output)
    if config is None:
        cp = Path(__file__).resolve().parents[1] / "context" / "board-config.json"
        config = json.loads(cp.read_text())

    ap = argparse.ArgumentParser()
    ap.add_argument("--fields", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    fields = json.loads(Path(args.fields).read_text())
    account = config["account"]
    repo = config["repo"]
    owner = config["project_owner"]
    board = config["board_number"]
    status_field = config.get("status_field", "Status")
    status_value = config.get("status_value", "Backlog")

    labels = fields.get("labels", [])
    title = fields["title"]
    fields.setdefault("meta", {})
    fields["meta"].update({"repo": repo, "column": status_value})
    body = render_issue_body(fields)

    auth_res = _gh(runner, ["gh", "auth", "status"])
    auth = auth_res.stdout or auth_res.stderr or ""
    active = parse_active_account(auth)
    issuing_account, need_switch, restore_to = resolve_issuing_account(
        auth, active, account, ("repo", "project"))
    if not args.dry_run and issuing_account is None:
        print("ERROR: no authenticated gh account on this machine carries the scopes "
              "[repo, project] needed to create the issue and place it on the board.\n"
              f"Run once, then re-run:\n  gh auth refresh -s project --user {account}")
        return 3

    if args.dry_run:
        print(f"[dry-run] repo: {repo}")
        print(f"[dry-run] account: issue as {issuing_account or active} "
              f"(switch={need_switch}; restore -> {restore_to})")
        bf = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False); bf.write(body); bf.close()
        print("[dry-run] would run: " + " ".join(build_create_argv(repo, title, bf.name, labels)))
        print(f"[dry-run] would add to board {board} and set {status_field}={status_value}")
        print("\n----- issue body -----\n" + body)
        return 0

    if need_switch:
        _gh(runner, ["gh", "auth", "switch", "--user", issuing_account])
    try:
        bf = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False); bf.write(body); bf.close()
        res = _gh(runner, build_create_argv(repo, title, bf.name, labels))
        if res.returncode != 0:
            stderr = (res.stderr or "").lower()
            if "not found" in stderr or "could not resolve" in stderr:
                print("ERROR: gh reported the repository was not found. This is almost "
                      f"always a WRONG-ACCOUNT error, not a missing repo. Active account "
                      f"must be {account}.")
            else:
                print(f"ERROR: gh issue create failed: {res.stderr}")
            return 4
        m = re.search(r"https://github\.com/\S+/issues/(\d+)", res.stdout)
        if not m:
            print("Issue created, but could not parse its URL:\n" + res.stdout)
            return 0
        issue_url, issue_number = m.group(0), int(m.group(1))
        print(f"Created issue: {issue_url}")

        items = json.loads(_gh(runner, ["gh", "project", "item-list", str(board),
                                        "--owner", owner, "--format", "json"]).stdout or "{}")
        item_id = issue_is_on_board(items, issue_number)
        proj = json.loads(_gh(runner, ["gh", "project", "view", str(board),
                                       "--owner", owner, "--format", "json"]).stdout or "{}")
        project_id = proj.get("id")
        if item_id is None:
            added = json.loads(_gh(runner, ["gh", "project", "item-add", str(board),
                                            "--owner", owner, "--url", issue_url,
                                            "--format", "json"]).stdout or "{}")
            item_id = added.get("id")
        flist = json.loads(_gh(runner, ["gh", "project", "field-list", str(board),
                                        "--owner", owner, "--format", "json"]).stdout or "{}")
        field_id, option_id = find_status_option(flist, status_field, status_value)
        if item_id and project_id and field_id and option_id:
            _gh(runner, ["gh", "project", "item-edit", "--id", item_id,
                         "--project-id", project_id, "--field-id", field_id,
                         "--single-select-option-id", option_id])
            print(f"Placed on board {board}: {status_field}={status_value}")
        else:
            print(f"WARNING: issue created and on the board, but could not set "
                  f"{status_field}={status_value} automatically. Set it manually.")
        return 0
    finally:
        if need_switch and restore_to:
            _gh(runner, ["gh", "auth", "switch", "--user", restore_to])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
