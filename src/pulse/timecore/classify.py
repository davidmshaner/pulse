"""classify.py — pure bucket-classification primitives. A session's own
auto-memory dir is resolved via Path.home() (portable across machines), not a
hardcoded absolute path."""
import re
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


# Catch-all global dirs (#55): EVERY session reads user-level skills and writes
# auto-memory under these, so a registry claim on the bare dir gains evidence
# from sessions that belong to other buckets. Deeper claims (a specific skill
# subfolder) are fine — only the exact bare-dir claim is rejected.
CATCHALL_GLOBAL_DIRS = frozenset({
    str(Path.home() / ".claude" / "projects"),
    str(Path.home() / ".claude" / "skills"),
})


def _is_catchall(src):
    return str(Path(src.rstrip("/")).expanduser()) in CATCHALL_GLOBAL_DIRS


# Git-worktree conventions (#69): harness repos run parallel work in worktrees
# that mirror the repo layout, so '<repo>/<marker>/<name>/<sub>' is the same
# logical location as '<repo>/<sub>'. '/.claude/worktrees/' is the Claude Code
# convention; '/.worktrees/' is the bare convention Pulse itself uses.
_WORKTREE_RE = re.compile(r"/(?:\.claude/worktrees|\.worktrees)/[^/]+")


def strip_worktree_segments(fp):
    """Collapse every '<repo>/<marker>/<worktree-name>' segment to '<repo>', so
    a file touched in a worktree matches the claims of its canonical repo
    location. Substituted to a fixpoint, so a collapse that splices a new
    marker into the path still fully normalizes. A segment sitting DIRECTLY
    under $HOME is left alone — '~/.claude/worktrees/...' is user-level tooling
    state, not a repo worktree, and grafting it onto $HOME would prefix-match
    unrelated registry buckets. A path with no worktree segment returns
    unchanged; a path ending AT the worktree name maps to the repo root."""
    home = str(Path.home())
    while True:
        def _repl(m, _fp=fp):
            return m.group(0) if _fp[:m.start()] == home else ""
        new = _WORKTREE_RE.sub(_repl, fp)
        if new == fp:
            return new
        fp = new


def _prefix_match(fp, base):
    # bool(base): a blank claim/exclusion (stray '' in config) must be inert,
    # not match every absolute path via startswith("/").
    return bool(base) and (fp == base or fp.startswith(base + "/"))


def _match_raw_path(raw, norm, flat_buckets_sorted, excluded_paths):
    """The shared two-leg matcher (#69/#71): claims and exclusions are checked
    against BOTH the raw path and its worktree-normalized form — the normalized
    leg gives canonical claims reach into worktree copies; the raw leg keeps a
    claim or exclusion that deliberately targets a path INSIDE a worktree
    working as written. Returns (bucket_path_tuple|None, excluded)."""
    for ex in excluded_paths:
        ex_n = ex.rstrip("/")
        if _prefix_match(raw, ex_n) or _prefix_match(norm, ex_n):
            return None, True
    for b in flat_buckets_sorted:
        for src in b["source_paths"]:
            src_n = src.rstrip("/")
            if _is_catchall(src_n):
                continue
            if _prefix_match(raw, src_n) or _prefix_match(norm, src_n):
                return tuple(b["path"]), False
    return None, False


def match_file_to_bucket(filepath, flat_buckets_sorted, excluded_paths):
    if not filepath or not filepath.startswith("/"):
        return None
    raw = filepath.rstrip("/")
    bucket, _excluded = _match_raw_path(raw, strip_worktree_segments(raw),
                                        flat_buckets_sorted, excluded_paths)
    return bucket


def catchall_claims(flat_buckets):
    """Registry hygiene (#55): every (bucket_path, source_path) claiming a bare
    catch-all global dir. Consumers warn on these — the matcher already refuses
    them as evidence, but the registry entry itself is the mistake to fix."""
    out = []
    for b in flat_buckets:
        for src in b["source_paths"]:
            if _is_catchall(src):
                out.append((tuple(b["path"]), src))
    return out


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


# Minimum-confidence floor (#57): a lone incidental read (weight 0.2) must not
# decide a session's bucket — the winning score has to exceed it (any edit, or
# two-plus reads). Sub-floor evidence is treated as no evidence so the session
# falls through to the launch-dir cascade like any other.
EVIDENCE_FLOOR = 0.2


def _score_files(sess, flat_buckets_sorted, excluded_paths):
    """Raw per-bucket evidence scores (edits 1.0, reads 0.2), no floor."""
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
    return scores


def _top_bucket(scores):
    max_s = max(scores.values())
    top = sorted([b for b, s in scores.items() if s == max_s], key=lambda b: -len(b))
    return list(top[0]), max_s


def classify_session_by_files(sess, flat_buckets_sorted, excluded_paths):
    scores = _score_files(sess, flat_buckets_sorted, excluded_paths)
    if not scores:
        return None, None
    top, max_s = _top_bucket(scores)
    if max_s <= EVIDENCE_FLOOR:
        return None, None
    return top, {str(k): v for k, v in scores.items()}


def encoded_matches(encoded, source_path):
    enc = lambda p: p.replace("/", "-").replace("_", "-").lstrip("-")
    e = encoded.lstrip("-")
    s = enc(source_path)
    return e == s or e.startswith(s + "-")


def classify_session_by_project_dir(sess, flat_buckets_sorted, excluded_paths):
    """Launch-dir prefix tier. When the session carries the raw `cwd` (scan
    cache v3, #71) it is matched as a real path — worktree segments normalized
    (#69), both raw and normalized legs like the file matcher, and no lossy
    dash-encoding (so '/x/beta-archive' can't land on '/x/beta'). Sessions
    without a cwd (old caches, old sessions.json) keep the encoded fallback."""
    cwd = (sess.get("cwd") or "").rstrip("/")
    if cwd:
        bucket, excluded = _match_raw_path(cwd, strip_worktree_segments(cwd),
                                           flat_buckets_sorted, excluded_paths)
        if excluded:
            return None, "excluded"
        if bucket:
            return list(bucket), "project_dir_prefix"
        # Deliberately NO encoded retry: the lossy fallback is the bug class
        # this tier replaces (a registry path spelled differently from disk
        # surfaces as needs_llm/RESOLVE instead of silently landing on a
        # dash-collision bucket).
        return None, "unknown"
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
    # Prefer the raw cwd (#71): real-path EXACT comparison, two legs — raw (so
    # a rule deliberately keyed on a worktree path itself keeps matching) and
    # worktree-normalized (so a session launched at <root>/.claude/worktrees/
    # <name> matches the <root> mapping). No dash-encoding on this side: enc()
    # is lossy ('/', '_', '.' collapse) and belongs only to the encoded-name
    # fallback below, where the '_'-preservation rationale actually applies.
    # Still EXACT — subdirs must not inherit.
    cwd = (sess.get("cwd") or "").rstrip("/")
    if cwd:
        norm = strip_worktree_segments(cwd)
        for path, bucket in launch_dir_exact.items():
            p = path.rstrip("/")
            if p and (cwd == p or norm == p):
                return [bucket] if isinstance(bucket, str) else list(bucket)
        return None
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


def classify_session(sess, flat_buckets_sorted, excluded_paths, launch_dir_exact):
    """The full session cascade, in shipping order: file_evidence ->
    project_dir_prefix -> launch_dir_exact -> needs_llm. Single source of
    truth shared by prematch.py and the golden-corpus replay (#58): a session
    is classified identically no matter which consumer asks.

    Returns (bucket_path|None, reason, evidence_scores). bucket_path is
    post-ROOT_REDIRECT. reason "excluded" means the launch dir is registry-
    excluded (callers drop the session entirely).

    Sub-floor evidence ("a whisper", e.g. one incidental read) cannot decide a
    session on its own, but it is weighed against the launch-dir bucket
    (hand-verdict policy from the golden corpus, #57): a whisper that refines
    the launch bucket into a descendant wins ("file_evidence_refined"); a
    whisper on a different branch makes the session deterministically
    ambiguous — the corpus holds confirmed sessions of that exact shape with
    opposite truths — so the cascade declines to needs_llm."""
    scores = _score_files(sess, flat_buckets_sorted, excluded_paths)
    whispers = []
    if scores:
        top, max_s = _top_bucket(scores)
        if max_s > EVIDENCE_FLOOR:
            return sc_root_to_internal(top), "file_evidence", {str(k): v for k, v in scores.items()}
        whispers = [list(k) for k in scores]
    b, reason = classify_session_by_project_dir(sess, flat_buckets_sorted, excluded_paths)
    if b:
        if whispers:
            # Every whisper bucket is weighed, not just the strongest: one
            # off-branch whisper is enough to make the session ambiguous,
            # regardless of dict ordering.
            def on_branch(w):
                return (w[:len(b)] == b) if len(w) > len(b) else (b[:len(w)] == w)
            if not all(on_branch(w) for w in whispers):
                return None, "needs_llm", {}
            desc = [w for w in whispers if len(w) > len(b)]
            if desc:
                deepest = max(desc, key=len)
                if all(deepest[:len(w)] == w for w in desc):
                    # a single chain below the launch bucket: refine to its tip
                    return sc_root_to_internal(deepest), "file_evidence_refined", {str(k): v for k, v in scores.items()}
                # sibling children: subtree agreed, child ambiguous — stay at b
        return sc_root_to_internal(b), reason, {}
    if reason == "excluded":
        return None, "excluded", {}
    b = classify_session_by_launch_dir_exact(sess, launch_dir_exact)
    if b:
        return sc_root_to_internal(b), "launch_dir_exact", {}
    return None, "needs_llm", {}


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
