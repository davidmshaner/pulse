"""test_scan_sessions_cache.py — guards the incremental parse cache (#30).

scan_sessions re-parsed every in-window JSONL on every 600s cycle. #30 splits the
expensive per-file EXTRACT (read + json.loads, window-independent, cacheable on
(path, mtime, size)) from the cheap per-window AGGREGATE (re-run each cycle). The
cache MUST be a pure speedup: byte-identical output to the uncached path.

All fixtures are SYNTHETIC and scrubbed — no real session content or client-name
paths (#8). The cache itself is privacy-sensitive (same as .cache/sessions.json)
and lives only under the caller-supplied cache path (gitignored .cache/).
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent / "src" / "pulse"
sys.path.insert(0, str(WIDGET))

import scan_sessions  # noqa: E402


# --- synthetic session builders --------------------------------------------

def _iso(dt):
    return dt.replace(microsecond=0).isoformat() + "Z"


def _session_entries(base):
    """A representative CLI session: a user turn, an assistant turn with token
    usage + Edit/Read/Bash tool_use, and a tool_result user turn (no text)."""
    return [
        {"timestamp": _iso(base), "type": "user", "uuid": "u-0",
         "message": {"id": "umsg-1", "content": [{"type": "text", "text": "kick off the task"}]}},
        {"timestamp": _iso(base + timedelta(minutes=1)), "type": "assistant",
         "message": {"id": "amsg-1",
                     "usage": {"input_tokens": 10, "output_tokens": 5,
                               "cache_creation_input_tokens": 2, "cache_read_input_tokens": 100},
                     "content": [
                         {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/proj/a.py"}},
                         {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/proj/b.py"}},
                         {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}},
                     ]}},
        {"timestamp": _iso(base + timedelta(minutes=2)), "type": "user",
         "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
        {"timestamp": _iso(base + timedelta(minutes=3)), "type": "assistant",
         "message": {"id": "amsg-2",
                     "usage": {"input_tokens": 3, "output_tokens": 8,
                               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 50},
                     "content": [{"type": "text", "text": "done"}]}},
    ]


def _write_session(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return path


def _projects_tree(tmp_path, n=3):
    """A projects root with n encoded session dirs, each holding one JSONL whose
    entries land ~1 hour ago (well inside a 30d window)."""
    root = tmp_path / "projects"
    base = datetime.utcnow() - timedelta(hours=1)
    for i in range(n):
        _write_session(root / f"-tmp-proj{i}" / f"sess{i}.jsonl",
                       _session_entries(base + timedelta(minutes=i)))
    return root


def _window():
    now = datetime.utcnow()
    return now - timedelta(days=30), now + timedelta(minutes=1)


# --- pure-speedup: byte-identical output cached vs uncached -----------------

def test_cached_output_byte_identical(tmp_path):
    root = _projects_tree(tmp_path)
    ws, we = _window()
    cache = tmp_path / "cache" / "scan_cache.json"

    uncached = scan_sessions.scan(ws, we, projects_dirs=[root], cache_path=None)
    cold = scan_sessions.scan(ws, we, projects_dirs=[root], cache_path=cache)      # miss -> populates
    warm = scan_sessions.scan(ws, we, projects_dirs=[root], cache_path=cache)      # hit  -> reuses

    dump = lambda o: json.dumps(o, indent=1, default=str, sort_keys=True)
    assert dump(cold) == dump(uncached)
    assert dump(warm) == dump(uncached)
    assert uncached["stats"]["parsed"] == 3


# --- warm cache skips the expensive extract --------------------------------

def test_warm_cache_skips_reextraction(tmp_path, monkeypatch):
    root = _projects_tree(tmp_path)
    ws, we = _window()
    cache = tmp_path / "scan_cache.json"

    calls = {"n": 0}
    real_extract = scan_sessions.extract_session

    def counting_extract(fp):
        calls["n"] += 1
        return real_extract(fp)

    monkeypatch.setattr(scan_sessions, "extract_session", counting_extract)

    scan_sessions.scan(ws, we, projects_dirs=[root], cache_path=cache)   # cold: 3 extracts
    assert calls["n"] == 3
    scan_sessions.scan(ws, we, projects_dirs=[root], cache_path=cache)   # warm: 0 extracts
    assert calls["n"] == 3


# --- invalidation: mtime change re-extracts one file -----------------------

def test_mtime_change_reextracts(tmp_path, monkeypatch):
    root = _projects_tree(tmp_path)
    ws, we = _window()
    cache = tmp_path / "scan_cache.json"

    scan_sessions.scan(ws, we, projects_dirs=[root], cache_path=cache)   # populate

    reextracted = []
    real_extract = scan_sessions.extract_session

    def spy(fp):
        reextracted.append(str(fp))
        return real_extract(fp)

    monkeypatch.setattr(scan_sessions, "extract_session", spy)

    changed = root / "-tmp-proj1" / "sess1.jsonl"
    os.utime(changed, (time.time() + 5, time.time() + 5))               # bump mtime

    scan_sessions.scan(ws, we, projects_dirs=[root], cache_path=cache)
    assert reextracted == [str(changed)], "only the mtime-changed file should re-extract"


# --- invalidation: deleted file drops out of the cache, no crash -----------

def test_deleted_file_pruned_from_cache(tmp_path):
    root = _projects_tree(tmp_path)
    ws, we = _window()
    cache = tmp_path / "scan_cache.json"

    scan_sessions.scan(ws, we, projects_dirs=[root], cache_path=cache)
    keys_before = set(json.loads(cache.read_text())["files"])
    assert len(keys_before) == 3

    gone = root / "-tmp-proj2" / "sess2.jsonl"
    gone.unlink()

    out = scan_sessions.scan(ws, we, projects_dirs=[root], cache_path=cache)
    assert out["stats"]["parsed"] == 2
    keys_after = set(json.loads(cache.read_text())["files"])
    assert str(gone) not in keys_after
    assert len(keys_after) == 2


# --- window slide: same cached extract, re-windowed each run ----------------

def test_window_slide_reaggregates_from_cache(tmp_path):
    """A file unchanged on disk (cache hit) but the window narrows so some of its
    entries fall out — aggregate must re-window from the full cached extract, so
    the cached result equals a fresh uncached parse for the narrow window."""
    root = tmp_path / "projects"
    base = datetime.utcnow() - timedelta(hours=2)
    _write_session(root / "-tmp-projx" / "s.jsonl", _session_entries(base))
    cache = tmp_path / "scan_cache.json"

    wide_ws, we = _window()
    scan_sessions.scan(wide_ws, we, projects_dirs=[root], cache_path=cache)   # warms full extract

    # Narrow window that excludes the first entry (base) but keeps the +3min one.
    narrow_ws = base + timedelta(minutes=1, seconds=30)
    cached = scan_sessions.scan(narrow_ws, we, projects_dirs=[root], cache_path=cache)
    fresh = scan_sessions.scan(narrow_ws, we, projects_dirs=[root], cache_path=None)

    dump = lambda o: json.dumps(o, indent=1, default=str, sort_keys=True)
    assert dump(cached) == dump(fresh)


# --- default cache path lives beside --out (under gitignored .cache/) -------

def test_default_cache_path_is_beside_out(tmp_path):
    out = tmp_path / ".cache" / "sessions.json"
    assert scan_sessions.default_cache_path(out) == tmp_path / ".cache" / "scan_cache.json"
