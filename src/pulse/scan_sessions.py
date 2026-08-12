#!/usr/bin/env python3
"""scan_sessions.py — /deploy-week Step 2a.

Walks ~/.claude/projects/ + ~/.claude/projects/-private-tmp/ for JSONL files,
slices entries to [window_start, window_end), extracts tool-call evidence +
metrics, classifies category (interactive/headless/subagent).

Parsing is split in two so unchanged files aren't re-read every refresh cycle (#30):

  * EXTRACT (``extract_session``) — read + json.loads every line into a compact,
    window-INDEPENDENT per-file record. This is the expensive step; it is cached on
    (path, mtime, size) under the gitignored .cache/ (``--cache``).
  * AGGREGATE (``aggregate_session``) — apply the rolling window (window_end=now
    moves every run), dedup, sum tokens, compute duration. Cheap; re-run each cycle.

The cache is a pure speedup: ``scan(...)`` yields byte-identical output whether or
not a cache path is supplied (see tests/test_scan_sessions_cache.py). Cache contents
are as privacy-sensitive as .cache/sessions.json (#8) — they live only under the
caller's cache path, are never logged, and are gitignored.

Usage:
  python3 scan_sessions.py --start 2026-04-13T08:00:00 --end 2026-04-20T11:22:00 --out data/sessions.json
"""
import argparse, json, os, sys
from collections import Counter
from datetime import datetime
from pathlib import Path

CACHE_VERSION = 3  # bump to invalidate every cached extract when the IR shape changes (v3: +cwd, #71)


def iso_to_dt(s):
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except Exception:
        return None


def classify_category(first_entry, filepath):
    if filepath and "/subagents/" in str(filepath):
        return "subagent"
    t = (first_entry or {}).get("type")
    if t == "queue-operation":
        return "headless"
    return "interactive"


def extract_session(filepath):
    """Window-independent read of one JSONL file → a compact per-entry record list.

    This is the cacheable half of the old ``parse_session``: it does the expensive
    read + json.loads and pre-extracts each entry's evidence, but applies NO window
    (the window moves every run and is applied cheaply in ``aggregate_session``).
    Returns ``{"first_type", "cwd", "entries": [...]}`` or ``None`` if the file
    is unreadable/gone (caller drops it — same as the old parse returning None).
    ``cwd`` (#71, cache v3) is the first non-sidechain cwd seen, pre-window.

    Text and bash commands are truncated to the same [:500]/[:300] bounds the old
    parser used, so nothing beyond what sessions.json already holds is cached (#8).
    """
    first_type = None
    first_seen = False
    cwd = None
    entries = []
    try:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if not first_seen:
                    first_type = e.get("type")   # first parseable line, pre-window (drives category)
                    first_seen = True
                if cwd is None and e.get("cwd") and not e.get("isSidechain"):
                    # First non-sidechain cwd seen, pre-window (#71): the raw
                    # launch dir the encoded parent-dir name lossily encodes —
                    # the launch-dir cascade needs the real path to strip
                    # worktree segments. Sidechain (subagent) entries can
                    # record a different directory; skip them.
                    cwd = e["cwd"]
                ts = iso_to_dt(e.get("timestamp"))
                if ts is None:
                    continue
                typ = e.get("type")
                msg = e.get("message") or {}
                rec = {"ts": ts.isoformat(), "typ": typ}
                if typ == "user":
                    content = msg.get("content")
                    is_tool_result = False
                    texts = []
                    if isinstance(content, str):
                        texts.append(content)
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict):
                                if c.get("type") == "tool_result":
                                    is_tool_result = True
                                elif c.get("type") == "text":
                                    texts.append(c.get("text") or "")
                    rec["is_tool_result"] = is_tool_result
                    rec["mid"] = msg.get("id") or e.get("uuid")   # None → noid fallback at aggregate
                    rec["texts"] = [t[:500] for t in texts]
                elif typ == "assistant":
                    rec["mid"] = msg.get("id") or e.get("uuid")
                    usage = msg.get("usage") or {}
                    rec["input_tok"] = usage.get("input_tokens", 0) or 0
                    rec["cache_creation_tok"] = usage.get("cache_creation_input_tokens", 0) or 0
                    rec["cache_read_tok"] = usage.get("cache_read_input_tokens", 0) or 0
                    rec["output_tok"] = usage.get("output_tokens", 0) or 0
                    edits, reads, bashes = [], [], []
                    content = msg.get("content")
                    if isinstance(content, list):
                        for c in content:
                            if not isinstance(c, dict) or c.get("type") != "tool_use":
                                continue
                            tool = c.get("name", "")
                            inp = c.get("input") or {}
                            fp = inp.get("file_path", "")
                            if tool in ("Edit", "Write", "NotebookEdit") and fp:
                                edits.append(fp)
                            elif tool == "Read" and fp:
                                reads.append(fp)
                            elif tool == "Bash":
                                cmd = inp.get("command", "")[:300]
                                if cmd:
                                    bashes.append(cmd)
                    rec["edits"] = edits
                    rec["reads"] = reads
                    rec["bashes"] = bashes
                entries.append(rec)
    except Exception:
        return None
    return {"first_type": first_type, "cwd": cwd, "entries": entries}


def aggregate_session(filepath, extracted, window_start, window_end):
    """Apply the rolling window to an extracted IR → the session dict (or None).

    Byte-identical to the old ``parse_session`` output for the same file+window;
    the dedup sets and running sums are rebuilt from the windowed entries in order,
    exactly as the inline parser did.
    """
    edit_paths = Counter()
    read_paths = Counter()
    bash_commands = []
    text_parts = []
    seen_asst_ids = set()
    user_msg_ids = set()
    input_tok = cache_creation_tok = cache_read_tok = output_tok = 0
    timestamps = []

    for rec in extracted["entries"]:
        ts = datetime.fromisoformat(rec["ts"])
        if not (window_start <= ts < window_end):
            continue
        timestamps.append(ts)
        typ = rec["typ"]
        if typ == "user":
            if not rec["is_tool_result"]:
                mid = rec["mid"] or f"noid-{rec['ts']}"
                if mid not in user_msg_ids:
                    user_msg_ids.add(mid)
                    for t in rec["texts"]:
                        text_parts.append(t[:500])
        elif typ == "assistant":
            mid = rec["mid"]
            if mid and mid in seen_asst_ids:
                continue
            if mid:
                seen_asst_ids.add(mid)
            input_tok += rec["input_tok"]
            cache_creation_tok += rec["cache_creation_tok"]
            cache_read_tok += rec["cache_read_tok"]
            output_tok += rec["output_tok"]
            for fp in rec["edits"]:
                edit_paths[fp] += 1
            for fp in rec["reads"]:
                read_paths[fp] += 1
            for cmd in rec["bashes"]:
                bash_commands.append(cmd)

    if not timestamps:
        return None

    category = classify_category({"type": extracted["first_type"]}, filepath)
    timestamps.sort()
    duration_min = 0.0
    prev = timestamps[0]
    for t in timestamps[1:]:
        gap = (t - prev).total_seconds() / 60
        if gap <= 15:
            duration_min += gap
        prev = t
    if len(user_msg_ids) >= 1 and duration_min < 1.0:
        duration_min = 1.0

    filepath = Path(filepath)
    text_blob = "\n".join(text_parts[:5]) + "\n" + "\n".join(bash_commands[:20])
    return {
        "filepath": str(filepath),
        "encoded": filepath.parent.name,
        "cwd": extracted.get("cwd"),
        "category": category,
        "edit_paths": dict(edit_paths),
        "read_paths": dict(read_paths),
        "bash_commands": bash_commands[:50],
        "text_blob": text_blob,
        "first_msg": (text_parts[0] if text_parts else "")[:180],
        "first_ts": timestamps[0].isoformat(),
        "last_ts": timestamps[-1].isoformat(),
        "metrics": {
            "user_msgs": len(user_msg_ids),
            "new_content_tokens": input_tok + cache_creation_tok + output_tok,
            "cache_read_tokens": cache_read_tok,
            "duration_minutes": round(duration_min, 2),
        },
    }


def parse_session(filepath, window_start, window_end):
    """Back-compat one-shot: extract then aggregate, no cache."""
    extracted = extract_session(filepath)
    if extracted is None:
        return None
    return aggregate_session(filepath, extracted, window_start, window_end)


# --- incremental parse cache (#30) -----------------------------------------

def default_cache_path(out_path):
    """The parse cache sits beside the sessions.json output (the gitignored
    .cache/ dir), so it inherits the same never-commit/never-log treatment (#8)."""
    return Path(out_path).parent / "scan_cache.json"


def _load_cache(cache_path):
    """Return {abs_path: {mtime, size, extracted}} for the current CACHE_VERSION, or
    {} on any miss (absent / unreadable / stale version). Never raises."""
    try:
        with open(cache_path) as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return {}
    files = data.get("files")
    return files if isinstance(files, dict) else {}


def _save_cache(cache_path, files):
    """Atomically persist the cache (only current candidates → deleted files are
    pruned). Best-effort: a cache write failure must never break the scan."""
    cache_path = Path(cache_path)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # PID suffix: two concurrent scanners must not race on one tmp name
        # and rename a truncated file over the cache.
        tmp = cache_path.with_suffix(f".{os.getpid()}.tmp")
        with open(tmp, "w") as f:
            json.dump({"version": CACHE_VERSION, "files": files}, f, default=str)
        tmp.rename(cache_path)
    except Exception:
        pass


def _iter_candidates(projects_dirs, window_start):
    """Yield (path, stat) for every JSONL whose mtime is in-window. Stat once here
    and reuse it as the cache key, so candidacy and the key agree on one reading."""
    for root in projects_dirs:
        if not root.exists():
            continue
        for p in root.rglob("*.jsonl"):
            try:
                st = p.stat()
            except Exception:
                continue
            if datetime.fromtimestamp(st.st_mtime) >= window_start:
                yield p, st


def scan(window_start, window_end, projects_dirs=None, cache_path=None):
    """Discover in-window JSONL candidates and build the sessions output dict.

    With ``cache_path`` set, unchanged files (same path+mtime+size) reuse their
    cached extract instead of being re-read; changed/new files re-extract; deleted
    files are pruned. Output is byte-identical to the ``cache_path=None`` path.
    """
    if projects_dirs is None:
        projects_dirs = [
            Path.home() / ".claude" / "projects",
            Path.home() / ".claude" / "projects" / "-private-tmp",
        ]

    old_cache = _load_cache(cache_path) if cache_path else {}
    new_cache = {}

    candidates = 0
    sessions = []
    for p, st in _iter_candidates(projects_dirs, window_start):
        candidates += 1
        key = str(p)
        extracted = None
        prior = old_cache.get(key)
        if prior and prior.get("mtime") == st.st_mtime and prior.get("size") == st.st_size:
            extracted = prior.get("extracted")
        if extracted is None:
            extracted = extract_session(p)
            if extracted is None:
                continue   # unreadable/deleted between discovery and read
        if cache_path:
            new_cache[key] = {"mtime": st.st_mtime, "size": st.st_size, "extracted": extracted}
        s = aggregate_session(p, extracted, window_start, window_end)
        if s:
            sessions.append(s)

    if cache_path:
        _save_cache(cache_path, new_cache)

    by_cat = Counter(s["category"] for s in sessions)
    stats = {
        "candidates": candidates,
        "parsed": len(sessions),
        "interactive": by_cat["interactive"],
        "headless": by_cat["headless"],
        "subagent": by_cat["subagent"],
    }
    return {"stats": stats, "sessions": sessions}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="ISO8601 window start (naive UTC)")
    ap.add_argument("--end", required=True, help="ISO8601 window end (naive UTC)")
    ap.add_argument("--out", required=True, help="output JSON path")
    ap.add_argument("--cache", help="parse-cache path (default: <out dir>/scan_cache.json)")
    ap.add_argument("--no-cache", action="store_true", help="disable the incremental parse cache")
    args = ap.parse_args()

    window_start = datetime.fromisoformat(args.start)
    window_end = datetime.fromisoformat(args.end)

    out_path = Path(args.out)
    if args.no_cache:
        cache_path = None
    else:
        cache_path = Path(args.cache) if args.cache else default_cache_path(out_path)

    out = scan(window_start, window_end, cache_path=cache_path)
    stats = out["stats"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1, default=str)

    print(f"CANDIDATES: {stats['candidates']}", file=sys.stderr)
    print(f"PARSED:     {stats['parsed']}", file=sys.stderr)
    print(f"  interactive: {stats['interactive']}", file=sys.stderr)
    print(f"  headless:    {stats['headless']}", file=sys.stderr)
    print(f"  subagent:    {stats['subagent']}", file=sys.stderr)
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
