"""test_scan_codex.py — guards the OpenAI Codex CLI usage scanner (#34).

Codex is Pulse's third usage surface (after Claude Code CLI + Cowork). A rollout
log at ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl already carries a top-level
UTC `timestamp` on every line (so time_math reads it in place, no normalized copy)
and a line-0 `session_meta` whose payload.cwd is the project dir (the bucket signal).

All fixtures here are SYNTHETIC and scrubbed — no real cwd / session content (#8).
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent / "src" / "pulse"
TIMECORE = WIDGET / "timecore"
sys.path.insert(0, str(WIDGET))
sys.path.insert(0, str(TIMECORE))

import scan_codex  # noqa: E402
from classify import walk_registry  # noqa: E402
from time_math import (  # noqa: E402
    compute_bucket_times,
    even_split_fractional,
    rollup_fractional,
)

# A tiny synthetic registry: one bucket rooted at a fake project dir.
REGISTRY = {
    "buckets": [
        {"name": "Acme", "source_path": "/tmp/pulse-codex-test/acme"},
    ]
}
FLAT = sorted(walk_registry(REGISTRY["buckets"]), key=lambda b: -b["depth"])


def _write_rollout(path: Path, cwd: str, ts_list, *, subagent=None):
    """Write a synthetic Codex rollout JSONL: line 0 session_meta, then one
    response_item per timestamp. `ts_list` are tz-aware datetimes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    meta_payload = {"id": "synthetic-uuid", "cwd": cwd, "originator": "codex_exec"}
    if subagent:
        meta_payload["source"] = {"subagent": subagent}
    lines.append({
        "timestamp": ts_list[0].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "type": "session_meta",
        "payload": meta_payload,
    })
    for t in ts_list:
        lines.append({
            "timestamp": t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": []},
        })
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return path


# --- session_meta / cwd extraction -----------------------------------------

def test_session_meta_reads_cwd(tmp_path):
    base = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    f = _write_rollout(tmp_path / "rollout-x.jsonl", "/tmp/pulse-codex-test/acme/sub", [base])
    meta = scan_codex._session_meta(f)
    assert meta is not None
    assert meta["cwd"] == "/tmp/pulse-codex-test/acme/sub"


def test_session_meta_missing_is_none(tmp_path):
    f = tmp_path / "rollout-empty.jsonl"
    f.write_text('{"timestamp":"2026-06-20T10:00:00Z","type":"response_item","payload":{}}\n')
    assert scan_codex._session_meta(f) is None


def test_session_meta_non_utf8_does_not_crash(tmp_path):
    # A partially-written / non-UTF-8 rollout (Codex mid-write) must skip the file,
    # never raise UnicodeDecodeError out of the scan and abort the whole snapshot.
    f = tmp_path / "rollout-bad.jsonl"
    f.write_bytes(b'\xff\xfe not valid utf-8 \x80\x81\n')
    assert scan_codex._session_meta(f) is None


# --- bucket resolution from cwd (reuses the registry classifiers) ----------

def test_cwd_under_source_path_resolves(tmp_path):
    bp = scan_codex._resolve_bucket("/tmp/pulse-codex-test/acme/clients/x", FLAT, [])
    assert bp == ["Acme"]


def test_unrelated_cwd_is_none(tmp_path):
    assert scan_codex._resolve_bucket("/tmp/somewhere/else", FLAT, []) is None


def test_sibling_dir_does_not_misresolve(tmp_path):
    # Regression: a sibling dir sharing a name prefix with a bucket's source_path
    # must NOT resolve to that bucket. The lossy encoded-form matcher would wrongly
    # match '...acme-archive' onto the '...acme' bucket via startswith(src + '-');
    # exact path matching rejects it.
    assert scan_codex._resolve_bucket("/tmp/pulse-codex-test/acme-archive", FLAT, []) is None


def test_excluded_cwd_is_none(tmp_path):
    bp = scan_codex._resolve_bucket(
        "/tmp/pulse-codex-test/acme/secret", FLAT, ["/tmp/pulse-codex-test/acme/secret"]
    )
    assert bp is None


# --- scan(): window pre-filter, discovery, drop-unresolved -----------------

def _recent_window():
    now = datetime.now(timezone.utc)
    return now - timedelta(days=7), now


def test_scan_finds_recent_rollout_in_bucket(tmp_path):
    start, end = _recent_window()
    mid = end - timedelta(hours=1)
    f = _write_rollout(
        tmp_path / "2026" / "06" / "20" / "rollout-a.jsonl",
        "/tmp/pulse-codex-test/acme/proj", [mid, mid + timedelta(minutes=5)],
    )
    os.utime(f, (mid.timestamp(), mid.timestamp()))
    out = scan_codex.scan(start, end, roots=[tmp_path], registry=REGISTRY)
    assert len(out) == 1
    s = out[0]
    assert s["bucket_path"] == ["Acme"]
    assert s["filepath"] == str(f)
    assert s["category"] == "codex"


def test_scan_skips_rollout_before_window(tmp_path):
    start, end = _recent_window()
    old = start - timedelta(days=30)
    f = _write_rollout(
        tmp_path / "2026" / "05" / "01" / "rollout-old.jsonl",
        "/tmp/pulse-codex-test/acme/proj", [old],
    )
    os.utime(f, (old.timestamp(), old.timestamp()))
    out = scan_codex.scan(start, end, roots=[tmp_path], registry=REGISTRY)
    assert out == []


def test_scan_drops_unresolved_cwd(tmp_path):
    start, end = _recent_window()
    mid = end - timedelta(hours=1)
    f = _write_rollout(
        tmp_path / "2026" / "06" / "20" / "rollout-u.jsonl",
        "/tmp/not-a-known-bucket", [mid],
    )
    os.utime(f, (mid.timestamp(), mid.timestamp()))
    out = scan_codex.scan(start, end, roots=[tmp_path], registry=REGISTRY)
    assert out == []


# --- the double-count watchout: same-bucket CLI+Codex overlap = once -------

def test_same_bucket_overlap_counts_once(tmp_path):
    """A /codex run shelled out from a Claude Code session overlaps the parent in
    wall-clock. Both resolve to the same bucket → counted once, not twice."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")
    start = datetime(2026, 6, 20, 0, 0, tzinfo=tz)
    end = datetime(2026, 6, 21, 0, 0, tzinfo=tz)
    t0 = datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc)
    # CLI-shape session file (top-level timestamp per line, same as codex).
    cli = tmp_path / "cli.jsonl"
    cli.write_text("\n".join(
        json.dumps({"timestamp": (t0 + timedelta(minutes=m)).isoformat().replace("+00:00", "Z")})
        for m in range(0, 21, 5)
    ) + "\n")
    # Codex rollout overlapping the same span.
    codex = _write_rollout(
        tmp_path / "rollout-c.jsonl", "/tmp/pulse-codex-test/acme",
        [t0 + timedelta(minutes=m) for m in range(0, 21, 5)],
    )
    sessions = [
        {"filepath": str(cli), "bucket_path": ["Acme"]},
        {"filepath": str(codex), "bucket_path": ["Acme"]},
    ]
    per_bucket, _ = compute_bucket_times(sessions, start, end, 15, tz)
    rolled = rollup_fractional(even_split_fractional(per_bucket))
    minutes = rolled[("Acme",)]
    # The union span is exactly 20 minutes; double-counting would yield 40.
    assert abs(minutes - 20.0) < 0.01
