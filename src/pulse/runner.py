"""runner.py — run the snapshot pipeline as a killable process group (#28).

Why this exists: app.py used to run snapshot.py via subprocess.run(..., timeout=120).
On timeout, subprocess.run SIGKILLs only the DIRECT child (snapshot.py) — the
grandchildren it spawned (scan_sessions.py, prematch.py, ...) are reparented to PID 1
and keep running. Each timed-out refresh cycle leaked one of these orphans; the orphans
competed for CPU and slowed the next cycle, which then also timed out and leaked another
— the compounding spiral that froze the menu-bar card for hours.

run_in_group fixes that: the child is started as its own session/process-group leader
(start_new_session=True), and on timeout the WHOLE group is killed (os.killpg), so no
grandchild survives. It also surfaces every non-clean outcome to a log instead of
swallowing it silently (the old `except: pass`), so a future jam is visible.

stdlib-only — app.py imports this before its pyobjc imports, and tests exercise it
without touching the UI stack.
"""
from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class SnapshotResult:
    ok: bool                 # ran to a clean exit (returncode 0, no timeout)
    timed_out: bool
    returncode: int | None
    stderr: str = ""


def _log(log_path: Path | None, msg: str) -> None:
    if log_path is None:
        return
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().isoformat(timespec="seconds")
        with open(log_path, "a") as f:
            f.write(f"{stamp} {msg}\n")
    except OSError:
        pass  # logging must never be the thing that breaks the refresh loop


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGKILL the child's whole process group, so orphaned grandchildren die too."""
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        # Leader already reaped; with start_new_session the pgid == the pid, so still
        # try that group — grandchildren may be reparented but share the group.
        pgid = proc.pid
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_in_group(cmd, timeout: float, log_path: Path | None = None) -> SnapshotResult:
    """Run `cmd` in its own process group; kill the entire group on timeout.

    Returns a SnapshotResult. Never raises for the expected failure modes (timeout,
    non-zero exit, missing binary) — the refresh loop reads the result and moves on.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,   # new session => child is its own process-group leader
        )
    except (OSError, ValueError) as e:
        _log(log_path, f"snapshot spawn failed: {e}")
        return SnapshotResult(ok=False, timed_out=False, returncode=None, stderr=str(e))

    try:
        _out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            proc.communicate(timeout=10)   # reap the leader after the group SIGKILL
        except subprocess.TimeoutExpired:
            pass
        _log(log_path, f"snapshot timeout after {timeout:.0f}s — killed process group")
        return SnapshotResult(ok=False, timed_out=True, returncode=None)

    rc = proc.returncode
    if rc != 0:
        tail = (err or b"").decode("utf-8", "replace").strip()[-500:]
        _log(log_path, f"snapshot exited {rc}: {tail}")
        return SnapshotResult(ok=False, timed_out=False, returncode=rc, stderr=tail)

    return SnapshotResult(ok=True, timed_out=False, returncode=0)
