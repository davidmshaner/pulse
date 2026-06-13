#!/usr/bin/env python3
"""scan_sessions.py — /deploy-week Step 2a.

Walks ~/.claude/projects/ + ~/.claude/projects/-private-tmp/ for JSONL files,
slices entries to [window_start, window_end), extracts tool-call evidence +
metrics, classifies category (interactive/headless/subagent).

Usage:
  python3 scan_sessions.py --start 2026-04-13T08:00:00 --end 2026-04-20T11:22:00 --out data/sessions.json
"""
import argparse, json, sys
from collections import Counter
from datetime import datetime
from pathlib import Path


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


def parse_session(filepath, window_start, window_end):
    first_entry = None
    edit_paths = Counter()
    read_paths = Counter()
    bash_commands = []
    text_parts = []
    seen_asst_ids = set()
    user_msg_ids = set()
    input_tok = cache_creation_tok = cache_read_tok = output_tok = 0
    timestamps = []

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
                if first_entry is None:
                    first_entry = e
                ts = iso_to_dt(e.get("timestamp"))
                if ts is None:
                    continue
                if not (window_start <= ts < window_end):
                    continue
                timestamps.append(ts)
                typ = e.get("type")
                msg = e.get("message") or {}
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
                    if not is_tool_result:
                        mid = msg.get("id") or e.get("uuid") or f"noid-{ts.isoformat()}"
                        if mid not in user_msg_ids:
                            user_msg_ids.add(mid)
                            for t in texts:
                                text_parts.append(t[:500])
                elif typ == "assistant":
                    mid = msg.get("id") or e.get("uuid")
                    if mid and mid in seen_asst_ids:
                        continue
                    if mid:
                        seen_asst_ids.add(mid)
                    usage = msg.get("usage") or {}
                    input_tok += usage.get("input_tokens", 0) or 0
                    cache_creation_tok += usage.get("cache_creation_input_tokens", 0) or 0
                    cache_read_tok += usage.get("cache_read_input_tokens", 0) or 0
                    output_tok += usage.get("output_tokens", 0) or 0
                    content = msg.get("content")
                    if isinstance(content, list):
                        for c in content:
                            if not isinstance(c, dict) or c.get("type") != "tool_use":
                                continue
                            tool = c.get("name", "")
                            inp = c.get("input") or {}
                            fp = inp.get("file_path", "")
                            if tool in ("Edit", "Write", "NotebookEdit") and fp:
                                edit_paths[fp] += 1
                            elif tool == "Read" and fp:
                                read_paths[fp] += 1
                            elif tool == "Bash":
                                cmd = inp.get("command", "")[:300]
                                if cmd:
                                    bash_commands.append(cmd)
    except Exception:
        return None

    if not timestamps:
        return None

    category = classify_category(first_entry, filepath)
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

    text_blob = "\n".join(text_parts[:5]) + "\n" + "\n".join(bash_commands[:20])
    return {
        "filepath": str(filepath),
        "encoded": filepath.parent.name,
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="ISO8601 window start (naive UTC)")
    ap.add_argument("--end", required=True, help="ISO8601 window end (naive UTC)")
    ap.add_argument("--out", required=True, help="output JSON path")
    args = ap.parse_args()

    window_start = datetime.fromisoformat(args.start)
    window_end = datetime.fromisoformat(args.end)

    projects_dirs = [
        Path.home() / ".claude" / "projects",
        Path.home() / ".claude" / "projects" / "-private-tmp",
    ]

    candidates = []
    for root in projects_dirs:
        if not root.exists():
            continue
        for p in root.rglob("*.jsonl"):
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
            except Exception:
                continue
            if mtime >= window_start:
                candidates.append(p)

    sessions = []
    for p in candidates:
        s = parse_session(p, window_start, window_end)
        if s:
            sessions.append(s)

    by_cat = Counter(s["category"] for s in sessions)
    stats = {
        "candidates": len(candidates),
        "parsed": len(sessions),
        "interactive": by_cat["interactive"],
        "headless": by_cat["headless"],
        "subagent": by_cat["subagent"],
    }

    out = {"stats": stats, "sessions": sessions}
    out_path = Path(args.out)
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
