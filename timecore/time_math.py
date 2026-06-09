"""time_math.py — pure interval/time-math primitives. Extracted verbatim from
deploy-week/scripts/render.py. No file-path policy beyond reading a JSONL given
an explicit filepath. Pure functions otherwise."""
import json
import datetime
from collections import defaultdict
from pathlib import Path


def parse_window_bound(s):
    """Parse ISO timestamp (naive or tz-aware). Assume naive strings are local ET."""
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # Assume local ET (-04:00); deploy-week invocations pass local-wall-clock bounds
        dt = dt.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=-4)))
    return dt


def collect_timestamps(filepath, window_start, window_end, local_tz):
    """Read a JSONL file, return sorted list of entry timestamps in the window (as tz-aware dts in local_tz)."""
    out = []
    try:
        with open(filepath) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    ts = obj.get("timestamp")
                    if not ts:
                        continue
                    dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if window_start <= dt <= window_end:
                        out.append(dt.astimezone(local_tz))
                except Exception:
                    continue
    except Exception:
        return []
    out.sort()
    return out


def intervals_from_timestamps(timestamps, gap_minutes):
    """Cluster sorted timestamps by gap → list of (start, end) intervals."""
    if not timestamps:
        return []
    out = []
    cur_s = timestamps[0]
    prev = timestamps[0]
    threshold_sec = gap_minutes * 60
    for t in timestamps[1:]:
        if (t - prev).total_seconds() > threshold_sec:
            out.append((cur_s, prev))
            cur_s = t
        prev = t
    out.append((cur_s, prev))
    return out


def union_minutes(intervals):
    """Merge overlapping intervals and sum their total minutes."""
    if not intervals:
        return 0.0
    sorted_ivs = sorted(intervals)
    merged = [list(sorted_ivs[0])]
    for s, e in sorted_ivs[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return sum((e - s).total_seconds() / 60 for s, e in merged)


def naive_minutes(intervals):
    """Sum interval lengths without merging (naive sum = parallel-inflated)."""
    return sum((e - s).total_seconds() / 60 for s, e in intervals)


def merge_intervals(intervals):
    """Merge overlapping intervals → sorted list of disjoint (start, end)."""
    if not intervals:
        return []
    sorted_ivs = sorted(intervals)
    merged = [list(sorted_ivs[0])]
    for s, e in sorted_ivs[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def even_split_fractional(per_bucket_intervals):
    """Even-split fractional (LOWER BOUND) via a sweep-line over interval endpoints.

    For every wall-clock instant, divide it equally among the leaf buckets that
    have a session active there. A segment of duration D with N active buckets
    gives D/N minutes to each of those N buckets.

    Using a sweep-line over actual endpoints (not an integer-minute grid) means
    the per-bucket fractional minutes sum EXACTLY to the global wall-clock union
    — no minute-rounding drift.

    Input:  {leaf_bucket_path: [(start, end), ...]}  (raw, may overlap within a bucket)
    Output: {leaf_bucket_path: fractional_minutes}
    """
    # Per-bucket, merge so a single bucket counts a clock-minute once (a bucket
    # running 2 parallel sessions of its own is still 1 unit of attention there).
    bucket_merged = {bp: merge_intervals(ivs) for bp, ivs in per_bucket_intervals.items()}

    # Collect every endpoint across all buckets → sweep boundaries.
    points = set()
    for ivs in bucket_merged.values():
        for s, e in ivs:
            points.add(s)
            points.add(e)
    points = sorted(points)

    frac = defaultdict(float)
    for i in range(len(points) - 1):
        seg_s, seg_e = points[i], points[i + 1]
        dur = (seg_e - seg_s).total_seconds() / 60
        if dur <= 0:
            continue
        # Which buckets are active across this whole segment?
        active = [bp for bp, ivs in bucket_merged.items()
                  if any(s <= seg_s and seg_e <= e for s, e in ivs)]
        if not active:
            continue
        share = dur / len(active)
        for bp in active:
            frac[bp] += share
    return dict(frac)


def rollup_fractional(leaf_fractional):
    """Roll leaf-bucket fractional minutes up to every ancestor path.

    Leaves are disjoint (each session has exactly one bucket_path), so a parent's
    fractional is simply the sum of its descendant leaves.
    """
    rolled = defaultdict(float)
    for bp, mins in leaf_fractional.items():
        for depth in range(1, len(bp) + 1):
            rolled[bp[:depth]] += mins
    return dict(rolled)


def compute_bucket_times(sessions, window_start, window_end, gap_minutes, local_tz):
    """Returns (per_bucket_intervals, all_intervals) where each value is a list of (start,end)."""
    per_bucket = defaultdict(list)
    all_intervals = []
    for s in sessions:
        fp = s.get("filepath")
        if not fp:
            continue
        ts = collect_timestamps(fp, window_start, window_end, local_tz)
        ivs = intervals_from_timestamps(ts, gap_minutes)
        bp = tuple(s.get("bucket_path", []))
        per_bucket[bp].extend(ivs)
        all_intervals.extend(ivs)
    return per_bucket, all_intervals


def collect_bucket_paths_with_ancestors(per_bucket):
    """For rollup: if [Acme,Group,Child] has intervals, also roll them up into [Acme,Group] and [Acme]."""
    rolled = defaultdict(list)
    for bp, ivs in per_bucket.items():
        for depth in range(1, len(bp) + 1):
            rolled[bp[:depth]].extend(ivs)
    return rolled
