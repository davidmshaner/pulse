"""timecore — deterministic time-math + bucket-classification primitives.

Canonical home of the pure functions used by deploy-week and Pulse. No file
I/O policy, no CLI, no David-specific paths in the math. Consumers add this
directory to sys.path and import from `timecore.time_math` / `timecore.classify`,
or import the flat names re-exported here.
"""
from .time_math import (  # noqa: F401
    parse_window_bound,
    collect_timestamps,
    intervals_from_timestamps,
    union_minutes,
    naive_minutes,
    merge_intervals,
    even_split_fractional,
    rollup_fractional,
    compute_bucket_times,
    collect_bucket_paths_with_ancestors,
)
from .classify import (  # noqa: F401
    walk_registry,
    match_file_to_bucket,
    classify_session_by_files,
    encoded_matches,
    classify_session_by_project_dir,
    sc_root_to_internal,
    classify_meeting,
)
