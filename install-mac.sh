#!/usr/bin/env bash
# Installs the Pulse LaunchAgent for the current user, pointing at this repo.
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
REPO_REAL="$(cd "$(dirname "$0")" && pwd -P)"   # physical path (symlinks resolved) — what launchd sees
PLIST="$HOME/Library/LaunchAgents/com.pulse.menubar.plist"

# Preflight: refuse a clone under a macOS TCC-protected folder. launchd's python
# cannot read ~/Documents, ~/Desktop, ~/Downloads, iCloud Drive, or the cloud
# providers under ~/Library/CloudStorage (Dropbox/OneDrive/Drive), so the
# KeepAlive LaunchAgent would crash-loop with an opaque "Operation not permitted".
# Catch it here, before any side effect. `bash install-mac.sh --check` runs only
# this preflight (exit 0 = installable, 1 = blocked) without installing.
shopt -s nocasematch    # the default macOS volume is case-insensitive (~/documents == ~/Documents)
_blocked=""
for _p in "$REPO/" "$REPO_REAL/"; do
  case "$_p" in
    "$HOME/Documents/"*|"$HOME/Desktop/"*|"$HOME/Downloads/"*|"$HOME/Library/Mobile Documents/"*|"$HOME/Library/CloudStorage/"*)
      _blocked=1 ;;
  esac
done
shopt -u nocasematch
if [ -n "$_blocked" ]; then
  cat >&2 <<EOF
ERROR: Pulse is cloned inside a macOS TCC-protected folder:
         $REPO
       launchd's python cannot read ~/Documents, ~/Desktop, ~/Downloads,
       iCloud Drive, or ~/Library/CloudStorage (Dropbox/OneDrive/Drive), so the
       menu-bar app would crash-loop with 'Operation not permitted'.
  Fix: move the clone outside those folders (e.g. ~/pulse or ~/dev/pulse)
       and re-run  bash install-mac.sh
EOF
  exit 1
fi
if [ "${1:-}" = "--check" ]; then
  echo "OK: $REPO is an installable location."
  exit 0
fi

mkdir -p "$REPO/.cache"

# Dependencies go in a repo-local venv built from the system python, so the
# interpreter that installs them is the exact one the LaunchAgent runs — no
# Homebrew/PEP-668 mismatch, and pyobjc is pinned to prebuilt-wheel versions
# (no clang source build on system Python 3.9). Failures are NOT swallowed: a
# broken dep install stops here with a clear error instead of surfacing later
# as a launch crash-loop.
if ! /usr/bin/python3 -c 'import sys' >/dev/null 2>&1; then
  echo "ERROR: /usr/bin/python3 is not usable. Install the macOS Command Line Tools" >&2
  echo "       (run: xcode-select --install) and re-run  bash install-mac.sh" >&2
  exit 1
fi
# Build the venv only when it's missing or its interpreter is broken — e.g. a
# macOS python upgrade can orphan a previous venv, leaving a dangling symlink.
# A healthy venv is reused; deps are (re)synced every run (a fast no-op when
# already satisfied). No `pip install --upgrade pip`: the venv's bundled pip
# installs the pinned wheels fine, and self-upgrading pip is an unpinned,
# network-dependent step that would now abort the whole install on failure.
if ! "$REPO/.venv/bin/python3" -c 'import sys' >/dev/null 2>&1; then
  /usr/bin/python3 -m venv --clear "$REPO/.venv"
fi
"$REPO/.venv/bin/python3" -m pip install --quiet -r "$REPO/requirements.txt"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.pulse.menubar</string>
  <key>ProgramArguments</key>
  <array><string>$REPO/.venv/bin/python3</string><string>-u</string><string>$REPO/src/pulse/app.py</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>StandardOutPath</key><string>$REPO/.cache/pulse.stdout.log</string>
  <key>StandardErrorPath</key><string>$REPO/.cache/pulse.stderr.log</string>
</dict>
</plist>
PLISTEOF
launchctl bootout "gui/$(id -u)/com.pulse.menubar" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/com.pulse.menubar"
echo "Pulse installed and started from $REPO"
