"""test_runner.py — the snapshot subprocess runner (#28).

The refresh jam: app.py ran snapshot.py under subprocess.run(timeout=120), which on
timeout SIGKILLs only the DIRECT child — the grandchild scan_sessions.py orphans to
PID 1 and keeps burning CPU, and each timed-out cycle leaks another. runner.run_in_group
must run the whole pipeline in its own process group and kill the GROUP on timeout, so
no grandchild survives. It must also surface failures (log), never swallow them silently.

stdlib-only by design — this test never imports pyobjc/rumps/app.py.
"""
import os
import sys
import time
import textwrap
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent / "src" / "pulse"
sys.path.insert(0, str(WIDGET))
import runner  # noqa: E402


def _alive(pid: int) -> bool:
    """True if pid is a live, non-zombie process we can signal."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_dead(pid: int, timeout: float = 4.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


def test_timeout_kills_whole_group_no_orphan(tmp_path):
    """A child that spawns a long-lived grandchild then sleeps: on timeout the
    grandchild must die too (the bug left it orphaned to PID 1)."""
    pidfile = tmp_path / "gc.pid"
    spawner = tmp_path / "spawner.py"
    spawner.write_text(textwrap.dedent("""
        import sys, time, subprocess
        gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        open(sys.argv[1], "w").write(str(gc.pid))
        time.sleep(120)
    """))
    log = tmp_path / "snap.log"

    res = runner.run_in_group(
        [sys.executable, str(spawner), str(pidfile)], timeout=1.5, log_path=log)

    assert res.timed_out is True
    assert res.ok is False
    gc_pid = int(pidfile.read_text().strip())
    assert _wait_dead(gc_pid), "grandchild survived — process group was not killed"
    # failure must be recorded, not swallowed
    assert log.exists() and "timeout" in log.read_text().lower()


def test_success_path():
    res = runner.run_in_group([sys.executable, "-c", "print('ok')"], timeout=15)
    assert res.ok is True
    assert res.timed_out is False
    assert res.returncode == 0


def test_nonzero_exit_is_logged(tmp_path):
    log = tmp_path / "snap.log"
    res = runner.run_in_group(
        [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
        timeout=15, log_path=log)
    assert res.ok is False
    assert res.timed_out is False
    assert res.returncode == 3
    assert log.exists() and log.read_text().strip() != ""
