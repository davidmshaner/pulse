#!/usr/bin/env python3
"""pulse_win.py — always-on-top overlay frontend (Windows; cross-platform via tkinter).

A small borderless, topmost window shows the Pulse headline. Click it to expand the
per-engagement breakdown; click again to collapse. Drag it to reposition. Right-click
to quit. Same state.json contract + cadence as the macOS menu bar (pulse.py).

Run:  pythonw pulse_win.py   (Windows, no console)
      python3 pulse_win.py   (testing on any OS)
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk

WIDGET_DIR = Path(__file__).resolve().parent
SNAPSHOT_SCRIPT = WIDGET_DIR / "snapshot.py"
sys.path.insert(0, str(WIDGET_DIR))
import frontend_common as fc  # noqa: E402
from live_bucket import detect as detect_live_bucket  # noqa: E402

LIVE_BUCKET_MS = 60_000
SNAPSHOT_MS = 600_000
POLL_MS = 2_000
SNAPSHOT_TIMEOUT = 120

BG = "#111111"
BG2 = "#1c1c1c"
FG = "#eeeeee"
FG2 = "#cccccc"
MONO = ("Menlo" if sys.platform == "darwin"
        else "Consolas" if sys.platform.startswith("win")
        else "DejaVu Sans Mono")


class PulseOverlay:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Pulse")
        self.root.attributes("-topmost", True)  # always on top
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.expanded = False
        self._snapshot_lock = threading.Lock()
        self._needs_repaint = False
        self._drag = (0, 0)

        self.headline = tk.Label(self.root, font=(MONO, 13), fg=FG, bg=BG,
                                 padx=12, pady=5, cursor="hand2")
        self.headline.pack(fill="x")
        self.detail = tk.Label(self.root, justify="left", anchor="w",
                               font=(MONO, 11), fg=FG2, bg=BG2, padx=12, pady=8)

        self.headline.bind("<ButtonPress-1>", self._press)
        self.headline.bind("<B1-Motion>", self._drag_move)
        self.headline.bind("<ButtonRelease-1>", self._release)
        self.root.bind("<Button-3>", lambda _e: self.root.destroy())

        self._moved = False
        self._state = fc.load_state(WIDGET_DIR)
        if self._state is None:
            self._run_snapshot()
            self._state = fc.load_state(WIDGET_DIR)
        self._repaint()
        # Borderless overlay on Windows (overrideredirect works there). On macOS the
        # same call leaves the window empty/broken, so keep the normal title bar.
        if sys.platform.startswith("win"):
            self.root.overrideredirect(True)
        self.root.geometry("+60+60")
        self.root.update_idletasks()
        self.root.lift()
        self.root.after(LIVE_BUCKET_MS, self._tick_live)
        self.root.after(SNAPSHOT_MS, self._tick_snapshot)
        self.root.after(POLL_MS, self._tick_poll)

    # --- drag + click ----------------------------------------------------
    def _press(self, e):
        self._drag = (e.x, e.y)
        self._moved = False

    def _drag_move(self, e):
        self._moved = True
        x = self.root.winfo_x() + e.x - self._drag[0]
        y = self.root.winfo_y() + e.y - self._drag[1]
        self.root.geometry(f"+{x}+{y}")

    def _release(self, _e):
        if not self._moved:
            self._toggle()

    def _toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.detail.pack(fill="x")
        else:
            self.detail.pack_forget()

    # --- paint -----------------------------------------------------------
    def _repaint(self):
        if self._state is not None:
            self._state["live_bucket"] = detect_live_bucket()
        self.headline.config(text=fc.title_for(self._state))
        lines = ["─" * 30 if l is None else l for l in fc.menu_lines(self._state)]
        self.detail.config(text="\n".join(lines))

    # --- snapshot --------------------------------------------------------
    def _run_snapshot(self) -> bool:
        try:
            subprocess.run([sys.executable, str(SNAPSHOT_SCRIPT)],
                           check=True, capture_output=True, timeout=SNAPSHOT_TIMEOUT)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def _run_snapshot_async(self):
        if not self._snapshot_lock.acquire(blocking=False):
            return

        def worker():
            try:
                self._run_snapshot()
                self._needs_repaint = True
            finally:
                self._snapshot_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    # --- timers ----------------------------------------------------------
    def _tick_live(self):
        self._repaint()
        self.root.after(LIVE_BUCKET_MS, self._tick_live)

    def _tick_snapshot(self):
        self._run_snapshot_async()
        self.root.after(SNAPSHOT_MS, self._tick_snapshot)

    def _tick_poll(self):
        if self._needs_repaint:
            self._needs_repaint = False
            self._state = fc.load_state(WIDGET_DIR)
            self._repaint()
        self.root.after(POLL_MS, self._tick_poll)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        o = PulseOverlay()

        def _check():
            try:
                print("MAINLOOP text:", repr(o.headline.cget("text")),
                      "mapped:", bool(o.headline.winfo_ismapped()),
                      "geom:", o.root.winfo_geometry())
            except Exception as e:
                print("MAINLOOP LABEL GONE:", type(e).__name__, e)
            o.root.destroy()

        o.root.after(1500, _check)
        o.root.mainloop()
    else:
        PulseOverlay().run()
