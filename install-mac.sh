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
# Ensure runtime deps (WebKit powers the designed popover panel).
/usr/bin/python3 -m pip install --user --quiet rumps pyyaml "pyobjc-framework-WebKit==11.1" || true
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.pulse.menubar</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>-u</string><string>$REPO/src/pulse/app.py</string></array>
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
