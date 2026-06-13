"""scan_cowork.py — discover Claude Cowork sessions and normalize them into the
same shape as Claude Code CLI sessions so the existing pipeline works unchanged.

Cowork stores sessions at:
  ~/Library/Application Support/Claude/local-agent-mode-sessions/
      <account-group>/<project>/local_<uuid>.json          ← manifest
      <account-group>/<project>/local_<uuid>/audit.jsonl   ← per-event log

The audit.jsonl is a per-event JSONL (one JSON per line) identical in spirit to
CLI's projects/.../<uuid>.jsonl, but the timestamp field is `_audit_timestamp`
instead of `timestamp`. We materialize a normalized copy at .cache/cowork-jsonls/
with `timestamp` renamed, so deploy-week's collect_timestamps() reads them as-is.

Classification: slash command in initialMessage > title regex > email default.
Cron-only sessions (sessionType='scheduled' with zero human user turns) drop.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

WIDGET_DIR    = Path(__file__).resolve().parent
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(WIDGET_DIR))
import config as _config  # noqa: E402
COWORK_ROOT   = _config.COWORK_ROOT
NORMALIZED    = _config.DATA_DIR / ".cache" / "cowork-jsonls"

# Bucket classifier ---------------------------------------------------------

# Classification maps are user-specific and live in config.yaml (cowork_classification),
# so this package ships generic. They alias to the config-loaded values.
SLASH_BUCKET = _config.COWORK_SLASH_BUCKET
EMAIL_DEFAULT = _config.COWORK_EMAIL_DEFAULT
TITLE_PATTERNS = _config.COWORK_TITLE_PATTERNS
CRON_TEMPLATES = _config.COWORK_CRON_TEMPLATES


def classify(manifest: dict) -> list[str] | None:
    initial = (manifest.get("initialMessage") or "").lstrip()
    m = re.match(r"^/([\w-]+)(?::|\s|$)", initial)
    if m and m.group(1) in SLASH_BUCKET:
        return SLASH_BUCKET[m.group(1)]
    title = manifest.get("title") or ""
    for pat, bucket in TITLE_PATTERNS:
        if pat.search(title):
            return bucket
    em = manifest.get("emailAddress")
    if em in EMAIL_DEFAULT:
        return EMAIL_DEFAULT[em]
    return None


# Audit-log reading + cron detection ----------------------------------------

def _is_human_user_turn(event: dict) -> bool:
    """User-typed message (string content, not a tool_result envelope)."""
    if event.get("type") != "user":
        return False
    content = (event.get("message") or {}).get("content")
    return isinstance(content, str)


def _is_cron_template(content: str) -> bool:
    return any(pat.match(content or "") for pat in CRON_TEMPLATES)


def _read_audit(audit_path: Path) -> list[dict]:
    if not audit_path.exists():
        return []
    out = []
    with open(audit_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _should_drop_as_cron(manifest: dict, events: list[dict]) -> bool:
    """Drop only if manifest tagged 'scheduled' AND no human user turns."""
    if manifest.get("sessionType") != "scheduled":
        return False
    for e in events:
        if not _is_human_user_turn(e):
            continue
        if not _is_cron_template((e.get("message") or {}).get("content", "")):
            return False
    return True


# Normalization -------------------------------------------------------------

def _normalize_audit(audit_events: list[dict], out_path: Path) -> tuple[str, str] | None:
    """Write audit events to out_path as a CLI-shape JSONL (timestamp field
    renamed). Returns (first_ts_iso, last_ts_iso) for window pre-filtering, or
    None if the audit had no usable timestamps."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    first = last = None
    tmp = out_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        for e in audit_events:
            raw = e.get("_audit_timestamp")
            if not raw:
                continue
            iso = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
            try:
                dt = datetime.fromisoformat(iso)
            except ValueError:
                continue
            iso_norm = dt.isoformat()
            if first is None or iso_norm < first:
                first = iso_norm
            if last is None or iso_norm > last:
                last = iso_norm
            normalized = dict(e)
            normalized["timestamp"] = iso_norm
            normalized.pop("_audit_timestamp", None)
            normalized.pop("_audit_hmac", None)
            f.write(json.dumps(normalized) + "\n")
    if first is None:
        tmp.unlink(missing_ok=True)
        return None
    tmp.rename(out_path)
    return first, last


# Public API ----------------------------------------------------------------

def scan(window_start: datetime, window_end: datetime) -> list[dict]:
    """Walk Cowork manifests, drop cron-only, classify, materialize normalized
    JSONLs, return a list of session dicts compatible with the CLI pipeline.

    Compatibility shape: {filepath, bucket_path, first_ts, last_ts, encoded,
    category} — only filepath + bucket_path are actually consumed by
    compute_bucket_times; the rest are for parity/diagnostics."""
    if not COWORK_ROOT.exists():
        return []

    window_start_ms = int(window_start.timestamp() * 1000)
    window_end_ms   = int(window_end.timestamp() * 1000)

    sessions: list[dict] = []
    for manifest_path in COWORK_ROOT.glob("*/*/local_*.json"):
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        last_activity = manifest.get("lastActivityAt", 0)
        created       = manifest.get("createdAt", 0)
        # Skip if session falls entirely outside the window
        if last_activity < window_start_ms or created > window_end_ms:
            continue

        audit_path = Path(str(manifest_path).removesuffix(".json")) / "audit.jsonl"
        events = _read_audit(audit_path)
        if _should_drop_as_cron(manifest, events):
            continue

        bucket = classify(manifest)
        if bucket is None:
            continue  # unclassifiable — skip rather than poison totals

        normalized_path = NORMALIZED / f"{manifest_path.stem}.jsonl"
        result = _normalize_audit(events, normalized_path)
        if result is None:
            continue
        first_ts, last_ts = result

        sessions.append({
            "filepath":    str(normalized_path),
            "bucket_path": bucket,
            "first_ts":    first_ts,
            "last_ts":     last_ts,
            "encoded":     f"cowork-{manifest_path.stem}",
            "category":    "cowork",
        })
    return sessions


if __name__ == "__main__":
    # Diagnostic: scan last 7d and print summary
    from datetime import timedelta
    LOCAL_TZ = datetime.now().astimezone().tzinfo
    end = datetime.now(LOCAL_TZ)
    start = end - timedelta(days=7)
    out = scan(start, end)
    print(f"found {len(out)} Cowork sessions in last 7d")
    for s in out:
        print(f"  {s['first_ts'][:19]}  bucket={'.'.join(s['bucket_path']):20}  {s['encoded']}")
