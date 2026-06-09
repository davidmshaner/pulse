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

import json
import subprocess
import sys
import threading
from pathlib import Path

import rumps

WIDGET_DIR = Path(__file__).resolve().parent
SNAPSHOT_SCRIPT = WIDGET_DIR / "snapshot.py"
STATE = WIDGET_DIR / "state.json"

sys.path.insert(0, str(WIDGET_DIR))
from live_bucket import detect as detect_live_bucket  # noqa: E402

LIVE_BUCKET_INTERVAL = 60     # seconds
SNAPSHOT_INTERVAL    = 600    # seconds (10 min)
SNAPSHOT_TIMEOUT     = 120    # seconds
REPAINT_POLL_INTERVAL = 2     # seconds; cheap bool check for finished snapshots


def bar(actual: float, total: float, width: int = 10) -> str:
    """High-contrast bar that reads in the macOS menu font.
    Solid block for filled, mid-dot for empty (▓/░ collapse into a gray blob)."""
    if total <= 0:
        return "·" * width
    frac = max(0.0, min(1.0, actual / total))
    n = int(round(frac * width))
    return "█" * n + "·" * (width - n)


def fmt_period(d: dict) -> str:
    if d["over"]:
        return f"OVER {d['hours_over']}h"
    return f"{d['hours_left']}h left"


def _info(text: str) -> "rumps.MenuItem":
    """Non-actionable info row. Without a callback, macOS renders MenuItems as
    disabled (low-contrast gray). A no-op callback makes them paint active."""
    return rumps.MenuItem(text, callback=lambda _: None)


def load_state() -> dict | None:
    if not STATE.exists():
        return None
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _abbr(name: str) -> str:
    """Two-char menu-bar abbreviation, derived generically (no hardcoded names)."""
    return name[:2]


def title_for(state: dict | None) -> str:
    """Short titles to survive the laptop menu bar / notch.
    Format budget: ~8 chars max. Use abbreviations + integer hours.
    Status is week-to-date (Mon 8am → now) vs weekly cap."""
    if state is None:
        return "Pulse"
    lb = state.get("live_bucket")
    engagements = state.get("engagements", {})

    # Live bucket matches an appetite engagement → show that engagement's status
    if lb and lb.get("bucket_path"):
        leaf = lb["bucket_path"][-1]
        if leaf in engagements:
            wtd = engagements[leaf]["wtd"]
            ab = _abbr(leaf)
            if wtd["over"]:
                return f"⚠{ab} -{wtd['hours_over']:.0f}h"
            return f"{ab} {wtd['hours_left']:.0f}h"

    # No live bucket OR live bucket has no appetite → fallback to worst over
    over = [(n, e["wtd"]["hours_over"]) for n, e in engagements.items() if e["wtd"]["over"]]
    if over:
        worst = max(over, key=lambda t: t[1])
        return f"⚠{_abbr(worst[0])} -{worst[1]:.0f}h"
    if engagements:
        total_left = sum(e["wtd"]["hours_left"] for e in engagements.values())
        return f"✓ {total_left:.0f}h"
    return "Pulse"


def menu_items(state: dict | None) -> list:
    """Returns a flat list of rumps.MenuItem (with rumps.separator markers)."""
    items: list = []
    if state is None:
        items.append(_info("(snapshot not yet run)"))
        return items

    # Top-level BILLABLE summary (sum of the appetite engagements vs total_budget)
    total = state.get("total")
    if total:
        wtd = total["wtd"]
        d7  = total["7d"]
        d30 = total["30d"]
        dot = "● " if wtd["over"] else "  "
        items.append(_info(
            f"{dot}BILLABLE  cap {total['weekly_cap_h']:.0f}h/wk  {total['monthly_cap_h']:.0f}h/mo"
        ))
        items.append(_info(
            f"  {bar(wtd['actual_h'], total['weekly_cap_h'])}  "
            f"wtd {wtd['actual_h']:.1f}/{total['weekly_cap_h']:.0f}h   {fmt_period(wtd)}"
        ))
        items.append(_info(
            f"  today {total['today_h']:.1f}h  ·  "
            f"7d {d7['actual_h']:.1f}h  ·  "
            f"30d {d30['actual_h']:.0f}/{total['monthly_cap_h']:.0f}h"
        ))
        items.append(rumps.separator)

    for name, eng in state["engagements"].items():
        wtd = eng["wtd"]
        d7  = eng["7d"]
        d30 = eng["30d"]
        dot = "● " if wtd["over"] else "  "
        items.append(_info(
            f"{dot}{name}  cap {eng['weekly_cap_h']:.1f}h/wk  {eng['monthly_cap_h']:.0f}h/mo"
        ))
        items.append(_info(
            f"  {bar(wtd['actual_h'], eng['weekly_cap_h'])}  "
            f"wtd {wtd['actual_h']:.1f}/{eng['weekly_cap_h']:.1f}h   {fmt_period(wtd)}"
        ))
        items.append(_info(
            f"  today {eng['today_h']:.1f}h  ·  "
            f"7d {d7['actual_h']:.1f}h  ·  "
            f"30d {d30['actual_h']:.0f}/{eng['monthly_cap_h']:.0f}h"
        ))
        items.append(rumps.separator)

    lb = state.get("live_bucket")
    if lb:
        bp_str = ".".join(lb.get("bucket_path") or ["?"])
        items.append(_info(f"NOW: {bp_str}  (~{lb['last_active_minutes_ago']:.0f} min)"))
    else:
        items.append(_info("NOW: (no recent activity)"))

    last_dw = state.get("last_deploy_week_run")
    if last_dw:
        items.append(_info(f"Last /deploy-week: {last_dw[:10]}"))

    n_sess = state.get("needs_llm", {}).get("sessions", 0)
    n_meet = state.get("needs_llm", {}).get("meetings", 0)
    if n_sess or n_meet:
        items.append(_info(
            f"uncategorized: {n_sess} sessions, {n_meet} meetings  (run /deploy-week)"
        ))

    generated = state.get("generated_at")
    if generated:
        items.append(_info(f"snapshot: {generated[11:16]}"))
    return items


class PulseApp(rumps.App):
    def __init__(self):
        super().__init__("Pulse", title="Pulse (loading…)")
        self._snapshot_lock = threading.Lock()
        self._needs_repaint = False
        self._state = load_state()
        # If no state yet, kick off a snapshot synchronously on first run.
        if self._state is None:
            self._run_snapshot()
            self._state = load_state()
        self._repaint_title()
        self._rebuild_menu()

    # --- repaint helpers --------------------------------------------------

    def _repaint_title(self):
        # Live bucket detection is cheap; do it inline.
        if self._state is not None:
            self._state["live_bucket"] = detect_live_bucket()
        self.title = title_for(self._state)

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
        self._state = load_state()
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
