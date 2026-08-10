#!/usr/bin/env python3
"""prematch.py — /deploy-week Step 3.

Applies deterministic categorization rules to sessions and meetings:
  1. File-path evidence vs bucket-registry source_paths (sessions)
  2. Attendee matches in learnings.yaml patterns (meetings)
  3. Domain matches in learnings.yaml domain_patterns (meetings)
  4. Solo / multi-bucket attendee rules
  5. Project-dir prefix fallback (sessions)
  6. Per-session manual overrides for needs_llm sessions (session-overrides.yaml, #64)

Items that match go into `confident`. Items that don't go into `needs_llm` for
the skill to hand off to free-text LLM matching (categorization.md rules).

Usage:
  python3 prematch.py --sessions data/sessions.json --meetings data/meetings.json \
      --registry context/bucket-registry.yaml --learnings context/learnings.yaml \
      --rules context/disambiguation-rules.yaml \
      --overrides session-overrides.yaml --out data/prematch.json
"""
import argparse, json, sys
from collections import Counter
from pathlib import Path

try:
    import yaml
except ImportError:
    print("MISSING_DEPS: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# timecore is vendored alongside this file (./timecore).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent / "timecore"))
from classify import (  # noqa: F401,E402
    walk_registry,
    match_file_to_bucket,
    classify_session_by_files,
    encoded_matches,
    classify_session_by_project_dir,
    classify_session_by_launch_dir_exact,
    sc_root_to_internal,
    classify_session,
    classify_meeting,
    catchall_claims,
)


def session_key(sess):
    """The stable per-session override key: the transcript JSONL basename.
    snapshot._session_brief surfaces the same key as `session_file` — the two
    must stay in lockstep or written overrides silently stop matching."""
    return Path(sess.get("filepath") or "").name or None


def load_session_overrides(path, out=sys.stderr):
    """session-overrides.yaml (#64) — {sessions: {<jsonl-basename>: [bucket, path]}}.
    Hand-edited user data (gitignored): a missing/empty file is the normal
    case, and a malformed one must degrade to a warning — this runs under
    snapshot's check=True, so an uncaught parse error kills every snapshot."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        print(f"WARNING: could not parse {p}: {e} — ignoring all overrides", file=out)
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("sessions") or {}, dict):
        print(f"WARNING: {p} is not a mapping with a 'sessions:' map — ignoring all overrides", file=out)
        return {}
    return data.get("sessions") or {}


def validate_session_overrides(overrides, flat_buckets, out=sys.stderr):
    """Drop entries whose value isn't a registered bucket path. A typo'd bucket
    would count hours under a phantom path no engagement matches — and the
    session would leave uncategorized.json, so nothing ever resurfaces the
    mistake. A dropped entry keeps its session needs_llm, so RESOLVE sees it
    again. Values normalize to a list (a bare string is a one-segment path)."""
    valid = {tuple(b["path"]) for b in flat_buckets}
    kept = {}
    for key, bucket in (overrides or {}).items():
        path = [bucket] if isinstance(bucket, str) else bucket
        if (isinstance(path, list) and path
                and all(isinstance(seg, str) for seg in path)
                and tuple(path) in valid):
            kept[key] = list(path)
        else:
            print(f"WARNING: session override {key!r} -> {bucket!r} is not a "
                  f"registered bucket path — ignored", file=out)
    return kept


def apply_session_override(sess, overrides):
    """Returns the (validated) override bucket path for this session, or None."""
    if not overrides:
        return None
    name = session_key(sess)
    if not name or name not in overrides:
        return None
    return list(overrides[name])


def warn_catchall_claims(flat_buckets, out=sys.stderr):
    """Registry hygiene (#55): a bare global-dir claim can't count as evidence
    (the matcher refuses it) — warn so the registry entry itself gets fixed."""
    for path, src in catchall_claims(flat_buckets):
        print(f"WARNING: bucket {' > '.join(path)} claims catch-all global dir "
              f"{src} — remove that claim from the registry; it cannot count as "
              f"evidence (#55)", file=out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", required=True)
    ap.add_argument("--meetings", required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--learnings", required=True)
    ap.add_argument("--rules", required=False, help="disambiguation-rules.yaml (read-only for now)")
    ap.add_argument("--overrides", required=False,
                    help="session-overrides.yaml — per-session hand verdicts (#64); "
                         "missing file is fine (most users have none)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.registry) as f:
        registry = yaml.safe_load(f)
    with open(args.learnings) as f:
        learnings = yaml.safe_load(f) or {}
    rules = {}
    if args.rules:
        with open(args.rules) as f:
            rules = yaml.safe_load(f) or {}
    launch_dir_exact = rules.get("session_launch_dir_exact") or {}
    flat_buckets_sorted = sorted(walk_registry(registry["buckets"]), key=lambda b: -b["depth"])
    session_overrides = validate_session_overrides(
        load_session_overrides(args.overrides), flat_buckets_sorted)
    warn_catchall_claims(flat_buckets_sorted)
    excluded_paths = registry.get("exclude_paths") or []

    with open(args.sessions) as f:
        sessions_data = json.load(f)
    with open(args.meetings) as f:
        meetings_data = json.load(f)

    # --- SESSIONS: only interactive get categorized
    sess_confident = []
    sess_needs_llm = []
    for s in sessions_data.get("sessions", []):
        if s.get("category") != "interactive":
            continue
        b, reason, scores = classify_session(s, flat_buckets_sorted, excluded_paths, launch_dir_exact)
        if reason == "excluded":
            continue
        if b is None:
            # Manual override (#64): fills ONLY the needs_llm gap — the shapes
            # the cascade intentionally declines (e.g. an off-branch sub-floor
            # read whisper). Real evidence above always wins, so a stale entry
            # can't mask a genuinely different session.
            ob = apply_session_override(s, session_overrides)
            if ob:
                b, reason = sc_root_to_internal(ob), "manual_override"
        s["bucket_path"] = b
        s["reason"] = reason
        s["evidence_scores"] = scores
        (sess_confident if b else sess_needs_llm).append(s)

    # --- MEETINGS
    meet_confident = []
    meet_needs_llm = []
    meet_solo = []
    for m in meetings_data.get("meetings", []):
        b, reason = classify_meeting(m, learnings)
        if reason == "solo":
            meet_solo.append(m)
            continue
        if b:
            m["bucket_path"] = b
            m["reason"] = reason
            meet_confident.append(m)
        else:
            m["bucket_path"] = None
            m["reason"] = reason
            meet_needs_llm.append(m)

    # --- distribution (confident only)
    dist = Counter()
    for s in sess_confident:
        dist[" > ".join(s["bucket_path"])] += 1
    for m in meet_confident:
        dist[" > ".join(m["bucket_path"])] += 1

    out = {
        "stats": {
            "sessions_total": len(sessions_data.get("sessions", [])),
            "sessions_interactive": sum(1 for s in sessions_data.get("sessions", []) if s.get("category") == "interactive"),
            "sessions_confident": len(sess_confident),
            "sessions_needs_llm": len(sess_needs_llm),
            "meetings_total": len(meetings_data.get("meetings", [])),
            "meetings_confident": len(meet_confident),
            "meetings_needs_llm": len(meet_needs_llm),
            "meetings_solo": len(meet_solo),
        },
        "distribution": dict(dist),
        "confident": {
            "sessions": sess_confident,
            "meetings": meet_confident,
        },
        "needs_llm": {
            "sessions": sess_needs_llm,
            "meetings": meet_needs_llm,
        },
        "solo_meetings": meet_solo,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1, default=str)

    print(f"Sessions: {out['stats']['sessions_confident']} confident, {out['stats']['sessions_needs_llm']} needs_llm", file=sys.stderr)
    print(f"Meetings: {out['stats']['meetings_confident']} confident, {out['stats']['meetings_needs_llm']} needs_llm, {out['stats']['meetings_solo']} solo", file=sys.stderr)
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
