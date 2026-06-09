#!/usr/bin/env python3
"""pulse.py — rumps menu bar app.

Three timers:
  - LIVE_BUCKET_INTERVAL (60s): cheap; re-detects current bucket, repaints title.
  - REPAINT_POLL_INTERVAL (2s): cheap bool check; repaints when a background
    snapshot has finished.
  - SNAPSHOT_INTERVAL (600s): kicks off snapshot.py in a background thread
    (never on the main thread — a ~23s sync run beachballs the app).

Run from terminal:
    python3 pulse.py

Quit via the menu bar's Quit item (added by rumps automatically).
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import rumps

WIDGET_DIR = Path(__file__).resolve().parent
SNAPSHOT_SCRIPT = WIDGET_DIR / "snapshot.py"

sys.path.insert(0, str(WIDGET_DIR))
from live_bucket import detect as detect_live_bucket  # noqa: E402
import frontend_common as fc  # noqa: E402

LIVE_BUCKET_INTERVAL = 60     # seconds
SNAPSHOT_INTERVAL    = 600    # seconds (10 min)
SNAPSHOT_TIMEOUT     = 120    # seconds
REPAINT_POLL_INTERVAL = 2     # seconds; cheap bool check for finished snapshots


def _info(text: str) -> "rumps.MenuItem":
    """Non-actionable info row. Without a callback, macOS renders MenuItems as
    disabled (low-contrast gray). A no-op callback makes them paint active."""
    return rumps.MenuItem(text, callback=lambda _: None)


def menu_items(state: dict | None) -> list:
    """Wrap the shared text lines into rumps MenuItems (None → separator)."""
    out = []
    for line in fc.menu_lines(state):
        out.append(rumps.separator if line is None else _info(line))
    return out


class PulseApp(rumps.App):
    def __init__(self):
        super().__init__("Pulse", title="Pulse (loading…)")
        self._snapshot_lock = threading.Lock()
        self._needs_repaint = False
        self._state = fc.load_state(WIDGET_DIR)
        # If no state yet, kick off a snapshot synchronously on first run.
        if self._state is None:
            self._run_snapshot()
            self._state = fc.load_state(WIDGET_DIR)
        self._repaint_title()
        self._rebuild_menu()

    # --- repaint helpers --------------------------------------------------

    def _repaint_title(self):
        # Live bucket detection is cheap; do it inline.
        if self._state is not None:
            self._state["live_bucket"] = detect_live_bucket()
        self.title = fc.title_for(self._state)

    def _rebuild_menu(self):
        # Remove every key rumps added (other than Quit which it auto-injects).
        for key in list(self.menu.keys()):
            del self.menu[key]
        for item in menu_items(self._state):
            if item is rumps.separator:
                self.menu.add(rumps.separator)
            else:
                self.menu.add(item)
        # Add manual refresh below everything else
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Refresh snapshot", callback=self._on_refresh))

    def _run_snapshot(self) -> bool:
        try:
            subprocess.run(
                ["python3", str(SNAPSHOT_SCRIPT)],
                check=True, capture_output=True, timeout=SNAPSHOT_TIMEOUT,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def _run_snapshot_async(self):
        """Run snapshot.py in a background thread; flag a repaint when done.

        snapshot.py takes ~20-30s. Running it synchronously on the main
        AppKit thread freezes the run loop (beachball) for the duration —
        all UI work stays on the main thread, the worker only sets a flag
        that _tick_repaint picks up.
        """
        if not self._snapshot_lock.acquire(blocking=False):
            return  # a snapshot is already running

        def worker():
            try:
                self._run_snapshot()
                # Repaint even on failure so any "Refreshing…" label resets.
                self._needs_repaint = True
            finally:
                self._snapshot_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    # --- callbacks --------------------------------------------------------

    @rumps.timer(LIVE_BUCKET_INTERVAL)
    def _tick_live(self, _):
        self._repaint_title()

    @rumps.timer(REPAINT_POLL_INTERVAL)
    def _tick_repaint(self, _):
        if not self._needs_repaint:
            return
        self._needs_repaint = False
        self._state = fc.load_state(WIDGET_DIR)
        self._repaint_title()
        self._rebuild_menu()

    @rumps.timer(SNAPSHOT_INTERVAL)
    def _tick_snapshot(self, _):
        self._run_snapshot_async()

    def _on_refresh(self, sender):
        sender.title = "Refreshing…"
        self._run_snapshot_async()


if __name__ == "__main__":
    PulseApp().run()
