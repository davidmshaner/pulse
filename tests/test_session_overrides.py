"""test_session_overrides.py — per-session manual overrides (#64).

The deterministic cascade intentionally declines whisper-ambiguous sessions
(off-branch sub-floor read → needs_llm). RESOLVE's teach levers all map folders
or attendees, so a user's hand verdict on a *specific session* needs its own
keyhole: a gitignored session-overrides.yaml mapping a session's JSONL basename
→ bucket path, applied ONLY where the cascade returns needs_llm. Real file
evidence still wins, so a stale override can't mask a genuinely different
session.
"""
import json
import subprocess
import sys
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent / "src" / "pulse"
sys.path.insert(0, str(WIDGET))

import config  # noqa: E402
import snapshot  # noqa: E402

REGISTRY_YAML = """
buckets:
- name: ClientA
  source_path: /Users/u/dev/clientA
- name: ClientB
  source_path: /Users/u/dev/clientB
"""

# The motivating shape: launched in ClientA's repo, only edit is its own
# auto-memory (absent here), only read is ONE reference file in ClientB's
# folder — a sub-floor off-branch whisper, so the cascade declines.
WHISPER_SESSION = {
    "filepath": "/Users/u/.claude/projects/-Users-u-dev-clientA/abc123.jsonl",
    "encoded": "-Users-u-dev-clientA",
    "category": "interactive",
    "edit_paths": {},
    "read_paths": {"/Users/u/dev/clientB/reference.md": 1},
}


def _run_prematch(tmp_path, sessions, overrides=None, overrides_path=None):
    """Run prematch.py the way snapshot does (subprocess) with tmp inputs.
    overrides=None → no --overrides flag at all; overrides_path → pass that
    path verbatim (e.g. a file that doesn't exist)."""
    paths = {}
    for name, payload in [
        ("sessions", {"sessions": sessions}),
        ("meetings", {"meetings": []}),
    ]:
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(payload))
        paths[name] = p
    reg = tmp_path / "registry.yaml"
    reg.write_text(REGISTRY_YAML)
    lea = tmp_path / "learnings.yaml"
    lea.write_text("patterns: {}\n")
    out = tmp_path / "prematch.json"
    cmd = [sys.executable, str(WIDGET / "prematch.py"),
           "--sessions", str(paths["sessions"]),
           "--meetings", str(paths["meetings"]),
           "--registry", str(reg),
           "--learnings", str(lea),
           "--out", str(out)]
    if overrides is not None:
        ov = tmp_path / "session-overrides.yaml"
        import yaml
        ov.write_text(yaml.safe_dump(overrides))
        cmd += ["--overrides", str(ov)]
    elif overrides_path is not None:
        cmd += ["--overrides", str(overrides_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f"prematch failed: {r.stderr}"
    return json.loads(out.read_text())


def test_whisper_ambiguous_session_is_needs_llm_without_override(tmp_path):
    # Baseline: guards that the fixture really is the declined shape — if the
    # cascade ever resolves it on its own, the override tests test nothing.
    res = _run_prematch(tmp_path, [dict(WHISPER_SESSION)])
    assert res["stats"]["sessions_needs_llm"] == 1


def test_override_resolves_needs_llm_session(tmp_path):
    res = _run_prematch(tmp_path, [dict(WHISPER_SESSION)],
                        overrides={"sessions": {"abc123.jsonl": ["ClientA"]}})
    assert res["stats"]["sessions_confident"] == 1
    (s,) = res["confident"]["sessions"]
    assert s["bucket_path"] == ["ClientA"]
    assert s["reason"] == "manual_override"


def test_override_does_not_beat_file_evidence(tmp_path):
    # A session with real edits in ClientB classifies there even if an override
    # names ClientA — overrides only fill the needs_llm gap, so a stale entry
    # can't mask a genuinely different session reusing the file name.
    sess = dict(WHISPER_SESSION)
    sess["edit_paths"] = {"/Users/u/dev/clientB/work.md": 3}
    res = _run_prematch(tmp_path, [sess],
                        overrides={"sessions": {"abc123.jsonl": ["ClientA"]}})
    (s,) = res["confident"]["sessions"]
    assert s["bucket_path"] == ["ClientB"]
    assert s["reason"] == "file_evidence"


def test_unmatched_override_entry_is_inert(tmp_path):
    # An entry for a session outside the scan window (or long gone) must not
    # crash or misroute anything.
    res = _run_prematch(tmp_path, [dict(WHISPER_SESSION)],
                        overrides={"sessions": {"other-session.jsonl": ["ClientB"]}})
    assert res["stats"]["sessions_needs_llm"] == 1


def test_missing_overrides_file_is_tolerated(tmp_path):
    # The file won't exist for most users — prematch must run normally.
    res = _run_prematch(tmp_path, [dict(WHISPER_SESSION)],
                        overrides_path=tmp_path / "nope.yaml")
    assert res["stats"]["sessions_needs_llm"] == 1


def test_session_without_filepath_is_tolerated(tmp_path):
    sess = dict(WHISPER_SESSION)
    del sess["filepath"]
    res = _run_prematch(tmp_path, [sess],
                        overrides={"sessions": {"abc123.jsonl": ["ClientA"]}})
    assert res["stats"]["sessions_needs_llm"] == 1


def test_config_exposes_overrides_path():
    # Same pattern as REGISTRY/RULES/GOLDEN: repo-local default, config.yaml
    # may relocate it. Never a literal repo-root path in consumers.
    assert isinstance(config.OVERRIDES, Path)
    assert config.OVERRIDES.name == "session-overrides.yaml"


def test_uncategorized_brief_carries_session_file(tmp_path):
    # RESOLVE keys an override on the JSONL basename, so the uncategorized
    # brief must surface it — otherwise the resolver has to dig through the
    # scan cache to find the identity the override needs.
    brief = snapshot._session_brief(dict(WHISPER_SESSION))
    assert brief["session_file"] == "abc123.jsonl"


def test_run_prematch_passes_overrides_path(monkeypatch):
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if "--out" in cmd:
            Path(cmd[cmd.index("--out") + 1]).write_text("{}")

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(snapshot.subprocess, "run", fake_run)
    snapshot.run_prematch(Path("/tmp/s.json"), Path("/tmp/m.json"))
    (cmd,) = calls
    assert "--overrides" in cmd
    assert cmd[cmd.index("--overrides") + 1] == str(config.OVERRIDES)
