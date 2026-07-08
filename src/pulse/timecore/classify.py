"""classify.py — pure bucket-classification primitives. A session's own
auto-memory dir is resolved via Path.home() (portable across machines), not a
hardcoded absolute path."""
from collections import defaultdict
from pathlib import Path


def walk_registry(buckets, parent_path=None):
    parent_path = parent_path or []
    out = []
    for b in buckets:
        path = parent_path + [b["name"]]
        sources = [b["source_path"]] + (b.get("additional_paths") or [])
        out.append({"path": path, "source_paths": sources, "depth": len(path)})
        if b.get("children"):
            out.extend(walk_registry(b["children"], path))
    return out


def match_file_to_bucket(filepath, flat_buckets_sorted, excluded_paths):
    if not filepath or not filepath.startswith("/"):
        return None
    fp = filepath.rstrip("/")
    for ex in excluded_paths:
        if fp == ex or fp.startswith(ex + "/"):
            return None
    for b in flat_buckets_sorted:
        for src in b["source_paths"]:
            src_n = src.rstrip("/")
            if fp == src_n or fp.startswith(src_n + "/"):
                return tuple(b["path"])
    return None


def _is_self_memory(filepath, encoded):
    """A session's own auto-memory lives at ~/.claude/projects/<encoded-cwd>/memory/.
    That path is structurally tied to the project cwd (always), so it's metadata
    about the session — not file evidence for what the session is *about*.
    Skip these from file_evidence scoring so the cwd-based project_dir_prefix
    fallback can correctly resolve the bucket."""
    if not encoded:
        return False
    self_prefix = f"{Path.home() / '.claude' / 'projects' / encoded / 'memory'}/"
    return filepath.startswith(self_prefix)


def classify_session_by_files(sess, flat_buckets_sorted, excluded_paths):
    encoded = sess.get("encoded", "")
    scores = defaultdict(float)
    for fp, count in (sess.get("edit_paths") or {}).items():
        if _is_self_memory(fp, encoded):
            continue
        b = match_file_to_bucket(fp, flat_buckets_sorted, excluded_paths)
        if b:
            scores[b] += count * 1.0
    for fp, count in (sess.get("read_paths") or {}).items():
        if _is_self_memory(fp, encoded):
            continue
        b = match_file_to_bucket(fp, flat_buckets_sorted, excluded_paths)
        if b:
            scores[b] += count * 0.2
    if not scores:
        return None, None
    max_s = max(scores.values())
    top = sorted([b for b, s in scores.items() if s == max_s], key=lambda b: -len(b))
    return list(top[0]), {str(k): v for k, v in scores.items()}


def encoded_matches(encoded, source_path):
    enc = lambda p: p.replace("/", "-").replace("_", "-").lstrip("-")
    e = encoded.lstrip("-")
    s = enc(source_path)
    return e == s or e.startswith(s + "-")


def classify_session_by_project_dir(sess, flat_buckets_sorted, excluded_paths):
    encoded = sess.get("encoded", "")
    for ex in excluded_paths:
        if encoded_matches(encoded, ex):
            return None, "excluded"
    for b in flat_buckets_sorted:
        for src in b["source_paths"]:
            if encoded_matches(encoded, src):
                return list(b["path"]), "project_dir_prefix"
    return None, "unknown"


def classify_session_by_launch_dir_exact(sess, launch_dir_exact):
    """EXACT launch-dir -> bucket fallback for sessions with no file evidence and
    no registry-prefix match.

    Unlike the registry (which prefix-matches via encoded_matches), this matches
    the launch dir EXACTLY. That lets an umbrella root -- a path that is the
    parent of many buckets, e.g. a monorepo root -- be mapped to a bucket WITHOUT
    its subdirectories inheriting the mapping (a prefix rule would wrongly grab
    every no-file-evidence session launched anywhere under that root). Intended
    for bare-root sessions whose only edits are their own auto-memory.

    `launch_dir_exact` maps an absolute path -> bucket path (list of segments,
    or a single string for a one-segment path). Both sides are normalized to the
    encoded form ('/', '_', '.' -> '-'); the session side too, because older
    ~/.claude/projects dirs preserve '_' while newer ones encode it."""
    if not launch_dir_exact:
        return None
    enc = lambda p: (
        p.replace("/", "-").replace("_", "-").replace(".", "-").lstrip("-")
    )
    e = enc(sess.get("encoded", ""))
    for path, bucket in launch_dir_exact.items():
        if e == enc(path.rstrip("/")):
            return [bucket] if isinstance(bucket, str) else list(bucket)
    return None


# Optional root-bucket re-routing: map a top-level bucket a session lands on
# exactly to a sub-bucket. Empty by default (generic); a consumer may populate it.
ROOT_REDIRECT: dict = {}


def sc_root_to_internal(path):
    """Re-route a path that lands exactly on a configured root bucket to its
    sub-bucket (via ROOT_REDIRECT). Generic no-op when ROOT_REDIRECT is empty."""
    key = tuple(path)
    if key in ROOT_REDIRECT:
        return list(ROOT_REDIRECT[key])
    return path


def classify_meeting(m, learnings):
    """Returns (bucket_path, reason) or (None, reason).

    Shape of learnings:
      patterns[email]          = [seg, seg, ...]     a single nested bucket path
      multi_bucket_attendees[email] = [[path1], [path2], ...]  list of candidate paths (ambiguous)
      domain_patterns[domain]  = [seg, seg, ...]     single path

    If ANY co-attendee is in multi_bucket_attendees, the meeting is ambiguous by
    definition and goes to needs_llm — the LLM uses other attendees and the title
    to pick which of the candidate paths applies.
    """
    if m.get("solo"):
        return None, "solo"

    patterns = learnings.get("patterns") or {}
    domain_patterns = learnings.get("domain_patterns") or {}
    multi_bucket = learnings.get("multi_bucket_attendees") or {}

    has_multi_bucket_attendee = False
    attendee_votes = defaultdict(int)

    for a in m.get("co_attendees", []):
        a_lower = a.lower()

        if a_lower in multi_bucket:
            has_multi_bucket_attendee = True
            continue

        if a_lower in patterns:
            path = patterns[a_lower]
            if isinstance(path, list):
                attendee_votes[tuple(path)] += 1
            elif isinstance(path, str):
                attendee_votes[(path,)] += 1
            continue

        domain = a_lower.split("@", 1)[-1] if "@" in a_lower else None
        if domain and domain in domain_patterns:
            d = domain_patterns[domain]
            if isinstance(d, list):
                attendee_votes[tuple(d)] += 1
            elif isinstance(d, str):
                attendee_votes[(d,)] += 1

    if has_multi_bucket_attendee:
        return None, "multi_bucket_needs_llm"

    if not attendee_votes:
        return None, "no_match"

    max_v = max(attendee_votes.values())
    top = sorted([b for b, v in attendee_votes.items() if v == max_v], key=lambda b: -len(b))
    if len(top) > 1:
        return None, "tie_needs_llm"
    return list(top[0]), "attendee_match"
