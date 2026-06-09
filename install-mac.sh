#!/usr/bin/env bash
# Installs the Pulse LaunchAgent for the current user, pointing at this repo.
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.pulse.menubar.plist"
mkdir -p "$REPO/.cache"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.pulse.menubar</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>-u</string><string>$REPO/pulse.py</string></array>
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
