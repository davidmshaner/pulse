#!/usr/bin/env python3
"""fetch_meetings.py — calendar fetcher (config-driven, optional).

Reads calendar accounts + self-emails from config.yaml's `calendar` section. If
no accounts are configured, emits an empty meetings file (sessions-only) so the
pipeline runs with zero calendar setup. When accounts ARE configured, fetches
events from each Google account via direct OAuth (the credential files written by
google_workspace_mcp), dedupes by event id, and annotates co-attendees / solo.

CLI matches the rest of the pipeline:
  python3 fetch_meetings.py --start <iso-tz> --end <iso-tz> --out <path>
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

WIDGET_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(WIDGET_DIR))
import config  # noqa: E402


def _write(out_path: Path, payload: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=1, default=str)


def load_creds(cred_dir: Path):
    if not cred_dir.exists():
        return None, None
    for p in cred_dir.glob("*.json"):
        try:
            with open(p) as f:
                data = json.load(f)
            if "token" in data or "refresh_token" in data:
                return data, p
        except Exception:
            continue
    return None, None


def fetch_calendar(src_tag, cred_dir, time_min, time_max):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    tokens, tok_path = load_creds(cred_dir)
    if not tokens:
        print(f"[{src_tag}] NO_CREDS in {cred_dir}", file=sys.stderr)
        return []

    creds = Credentials(
        token=tokens.get("token"),
        refresh_token=tokens.get("refresh_token"),
        token_uri=tokens.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=tokens.get("client_id"),
        client_secret=tokens.get("client_secret"),
        scopes=tokens.get("scopes", ["https://www.googleapis.com/auth/calendar.readonly"]),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tokens["token"] = creds.token
        with open(tok_path, "w") as f:
            json.dump(tokens, f)

    svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
    resp = svc.events().list(
        calendarId="primary", timeMin=time_min, timeMax=time_max,
        singleEvents=True, orderBy="startTime", maxResults=250,
    ).execute()

    events = []
    for e in resp.get("items", []):
        events.append({
            "id": e.get("id"),
            "title": e.get("summary", "(no title)"),
            "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
            "end":   e.get("end", {}).get("dateTime")   or e.get("end", {}).get("date"),
            "attendees": [a.get("email") for a in e.get("attendees", []) if a.get("email")],
            "organizer": (e.get("organizer") or {}).get("email"),
            "src": src_tag,
        })
    return events


def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s if "T" in s else s + "T00:00:00")
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out_path = Path(args.out)

    accounts = config.CALENDAR_ACCOUNTS
    self_emails = set(config.CALENDAR_SELF_EMAILS)

    # No calendar configured → sessions-only (zero setup for the user).
    if not accounts:
        _write(out_path, {"stats": {"meetings": 0, "note": "calendar_not_configured"}, "meetings": []})
        print("calendar not configured — wrote empty meetings")
        return

    # google libs only needed when calendar IS configured.
    try:
        import google.oauth2.credentials  # noqa: F401
        import googleapiclient.discovery   # noqa: F401
    except ImportError:
        print("MISSING_DEPS: pip install google-auth google-auth-oauthlib google-api-python-client",
              file=sys.stderr)
        _write(out_path, {"stats": {"meetings": 0, "note": "calendar_deps_missing"}, "meetings": []})
        return

    per_cal = {}
    for src_tag, cred_dir in accounts:
        per_cal[src_tag] = fetch_calendar(src_tag, cred_dir, args.start, args.end)
        print(f"[{src_tag}] {len(per_cal[src_tag])} events", file=sys.stderr)

    by_id = {}
    for src_tag, events in per_cal.items():
        for e in events:
            eid = e["id"]
            if eid in by_id:
                existing = by_id[eid]
                if len(e["attendees"]) > len(existing["attendees"]):
                    existing["attendees"] = e["attendees"]
                existing["src_calendars"].append(src_tag)
            else:
                by_id[eid] = {**e, "src_calendars": [src_tag]}

    meetings = []
    for m in by_id.values():
        co = [a for a in m["attendees"] if a not in self_emails]
        m["co_attendees"] = co
        m["solo"] = len(co) == 0
        s_dt, e_dt = parse_dt(m["start"]), parse_dt(m["end"])
        m["duration_min"] = round((e_dt - s_dt).total_seconds() / 60, 1) if (s_dt and e_dt) else 0.0
        meetings.append(m)
    meetings.sort(key=lambda m: m["start"] or "")

    stats = {
        "per_calendar": {k: len(v) for k, v in per_cal.items()},
        "raw_total": sum(len(v) for v in per_cal.values()),
        "deduped": len(meetings),
        "solo": sum(1 for m in meetings if m["solo"]),
        "real": sum(1 for m in meetings if not m["solo"]),
        "meetings": len(meetings),
    }
    _write(out_path, {"stats": stats, "meetings": meetings})
    print(f"DEDUPED: {stats['deduped']} (real={stats['real']}, solo={stats['solo']})", file=sys.stderr)


if __name__ == "__main__":
    main()
