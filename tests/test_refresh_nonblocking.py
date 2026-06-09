#!/usr/bin/env python3
"""test_refresh_nonblocking.py — regression test for the refresh beachball.

snapshot.py takes ~23s. The original _on_refresh ran it via a synchronous
subprocess.run on the main AppKit thread, freezing the run loop (beachball)
for the full duration — on every manual refresh AND every 600s timer tick.

Fix: _run_snapshot_async runs the subprocess in a daemon thread and sets
_needs_repaint when done; a main-thread timer picks up the flag and repaints.
This test binds the real methods to a bare harness object (no NSStatusItem)
and asserts:
  1. _run_snapshot_async returns in well under a second (non-blocking)
  2. _needs_repaint flips to True once the background snapshot completes
  3. a second call while one is running is a no-op (no thread pile-up)

Run: python3 tests/test_refresh_nonblocking.py
"""
from __future__ import annotations

import sys
import threading
import time
import types
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WIDGET))

import pulse  # noqa: E402


def make_harness():
    h = types.SimpleNamespace()
    h._snapshot_lock = threading.Lock()
    h._needs_repaint = False
    h._run_snapshot = types.MethodType(pulse.PulseApp._run_snapshot, h)
    h._run_snapshot_async = types.MethodType(pulse.PulseApp._run_snapshot_async, h)
    return h


def main() -> int:
    h = make_harness()

    # 1. Non-blocking: must return immediately, not after the ~23s snapshot.
    t0 = time.monotonic()
    h._run_snapshot_async()
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, f"_run_snapshot_async blocked for {elapsed:.1f}s"
    print(f"PASS  returns in {elapsed*1000:.0f}ms (non-blocking)")

    # 3. Re-entry guard: second call while running must be a no-op.
    before = threading.active_count()
    h._run_snapshot_async()
    after = threading.active_count()
    assert after <= before, "second call spawned a duplicate snapshot thread"
    print("PASS  concurrent call is a no-op")

    # 2. Flag set after background completion (snapshot takes ~23s; allow 120s
    #    to match SNAPSHOT_TIMEOUT).
    deadline = time.monotonic() + pulse.SNAPSHOT_TIMEOUT + 5
    while time.monotonic() < deadline:
        if h._needs_repaint:
            break
        time.sleep(0.5)
    assert h._needs_repaint, "_needs_repaint never set after background snapshot"
    print("PASS  _needs_repaint set after completion")

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
