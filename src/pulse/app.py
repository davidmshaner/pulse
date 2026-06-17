#!/usr/bin/env python3
"""panel_app.py — Pulse menu-bar app with a designed popover (WKWebView).

Backend unchanged: shells out to snapshot.py (same as pulse.py did), reads
state.json, renders the brand card, shows it in a transient popover.

Run: /usr/bin/python3 panel_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
SNAPSHOT_SCRIPT = PKG_DIR / "snapshot.py"
sys.path.insert(0, str(PKG_DIR))

# Preflight BEFORE the heavy pyobjc imports below: if a dep is missing or the
# working dir is unreadable, emit one clear line instead of a raw traceback into a
# KeepAlive crash loop. `--selftest` runs the checks and exits without starting the
# app. preflight is stdlib-only, so it imports even when the real deps are absent.
import preflight  # noqa: E402
preflight.run_or_exit(working_dir=PKG_DIR.parents[1], selftest="--selftest" in sys.argv)

import json          # noqa: E402
import threading     # noqa: E402

import AppKit        # noqa: E402
import WebKit        # noqa: E402
import objc          # noqa: E402
from Foundation import NSObject, NSMakeRect, NSMakeSize, NSURL, NSTimer  # noqa: E402

import config                                          # noqa: E402
import runner                                           # noqa: E402
from panel.render_state import build_view_model       # noqa: E402
from panel.render_html import write_rendered, RENDERED_PATH  # noqa: E402
import frontend_common as fc                           # noqa: E402
from live_bucket import detect as detect_live_bucket   # noqa: E402

STATE = config.DATA_DIR / "state.json"
SNAPSHOT_LOG = config.DATA_DIR / ".cache" / "snapshot.log"

SNAPSHOT_INTERVAL = 600.0   # seconds — how often the pipeline runs
# Hard ceiling on one pipeline run. Safe to keep well under the interval now that a
# timeout kills the whole process group (runner.run_in_group): a slow cycle no longer
# leaks orphans, so generous headroom costs only a later repaint, never a CPU spiral.
# 300s clears the measured ~60s light-load run with margin for a loaded machine; the
# durable cost reduction (incremental scan cache) is tracked as a follow-up. Issue #28.
SNAPSHOT_TIMEOUT = 300.0
LIVE_INTERVAL = 60.0        # seconds — repaint title glyph


def _load_state() -> dict | None:
    try:
        with open(STATE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, _notification):
        self._lock = threading.Lock()
        self.statusitem = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength)
        btn = self.statusitem.button()
        btn.setTarget_(self)
        btn.setAction_(objc.selector(self.toggle_, signature=b"v@:@"))

        self.webview = WebKit.WKWebView.alloc().initWithFrame_(NSMakeRect(0, 0, 360, 460))
        vc = AppKit.NSViewController.alloc().init()
        vc.setView_(self.webview)
        self.popover = AppKit.NSPopover.alloc().init()
        self.popover.setContentSize_(NSMakeSize(360, 460))
        self.popover.setContentViewController_(vc)
        self.popover.setBehavior_(AppKit.NSPopoverBehaviorTransient)

        # First paint: if no state, run snapshot synchronously once.
        if _load_state() is None:
            self._run_snapshot()
        self._repaint()

        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            LIVE_INTERVAL, self, objc.selector(self.tickLive_, signature=b"v@:@"), None, True)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            SNAPSHOT_INTERVAL, self, objc.selector(self.tickSnapshot_, signature=b"v@:@"), None, True)

    # --- painting ---------------------------------------------------------
    def _repaint(self):
        state = _load_state()
        if state is not None:
            state["live_bucket"] = detect_live_bucket()
        self.statusitem.button().setTitle_(fc.title_for(state, stale=fc.is_stale(state)))
        if state is not None:
            write_rendered(build_view_model(state))
        self.webview.loadFileURL_allowingReadAccessToURL_(
            NSURL.fileURLWithPath_(str(RENDERED_PATH)),
            NSURL.fileURLWithPath_(str(PKG_DIR / "panel")))

    # --- snapshot ---------------------------------------------------------
    def _run_snapshot(self) -> None:
        # sys.executable, not a hardcoded /usr/bin/python3: the LaunchAgent runs
        # app.py under the repo's .venv, so snapshot must run there too — the venv
        # is where the deps live. snapshot.py then propagates sys.executable to its
        # own children, keeping the whole pipeline on one interpreter.
        #
        # run_in_group runs the pipeline as its own process group and kills the GROUP
        # on timeout, so a slow scan_sessions can't orphan to PID 1 and leak CPU.
        # Failures are logged (not swallowed) so a stalled refresh is diagnosable.
        runner.run_in_group([sys.executable, str(SNAPSHOT_SCRIPT)],
                            timeout=SNAPSHOT_TIMEOUT, log_path=SNAPSHOT_LOG)

    def _snapshot_async(self):
        if not self._lock.acquire(blocking=False):
            return

        def worker():
            try:
                self._run_snapshot()
            finally:
                self._lock.release()
                # repaint must happen on the main thread
                AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(self._repaint)
        threading.Thread(target=worker, daemon=True).start()

    # --- timers / actions -------------------------------------------------
    def tickLive_(self, _timer):
        state = _load_state()
        if state is not None:
            state["live_bucket"] = detect_live_bucket()
        self.statusitem.button().setTitle_(fc.title_for(state, stale=fc.is_stale(state)))

    def tickSnapshot_(self, _timer):
        self._snapshot_async()

    def toggle_(self, sender):
        if self.popover.isShown():
            self.popover.performClose_(sender)
        else:
            self._repaint()
            self.popover.showRelativeToRect_ofView_preferredEdge_(
                sender.bounds(), sender, AppKit.NSRectEdgeMinY)


def main():
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    main()
