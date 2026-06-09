#!/usr/bin/env python3
"""fetch_meetings.py — STUB. Calendar is not wired in this release; this emits an
empty meetings file so the snapshot pipeline runs sessions-only. The real
OAuth-backed fetcher arrives with the calendar phase. CLI matches the real one."""
import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump({"stats": {"meetings": 0, "note": "calendar_not_configured"}, "meetings": []}, f)
    print("wrote empty meetings (calendar not configured)")


if __name__ == "__main__":
    main()
