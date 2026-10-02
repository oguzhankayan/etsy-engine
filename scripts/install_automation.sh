#!/bin/zsh
# Install launchd agents for the engine's learning loop.
#   daily  09:00 — metrics + rank-track   (com.etsy-engine.daily)
#   weekly Mon 09:30 — learn + renew      (com.etsy-engine.weekly)
# launchd (unlike cron) fires missed jobs on wake, which matters on a laptop.
# Re-run this script any time; it overwrites + reloads the agents.
set -eu
REPO="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS"

write_plist() {  # $1=label $2=script $3=calendar-xml
  cat > "$AGENTS/$1.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>$REPO/scripts/$2</string></array>
  <key>StartCalendarInterval</key>
  $3
  <key>StandardOutPath</key><string>$REPO/data/logs/launchd.log</string>
  <key>StandardErrorPath</key><string>$REPO/data/logs/launchd.log</string>
</dict>
</plist>
EOF
  launchctl unload "$AGENTS/$1.plist" 2>/dev/null || true
  launchctl load "$AGENTS/$1.plist"
  echo "loaded $1"
}

write_plist "com.etsy-engine.daily" "automation_daily.sh" \
  "<dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>"

write_plist "com.etsy-engine.weekly" "automation_weekly.sh" \
  "<dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>"

# Hourly pin publisher: drains the Pinterest queue at a human cadence
# (StartInterval instead of calendar so it also fires soon after wake).
cat > "$AGENTS/com.etsy-engine.pinspread.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.etsy-engine.pinspread</string>
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>-c</string>
    <string>cd $REPO &amp;&amp; .venv/bin/etsy-engine pin-spread --limit 3 >> data/logs/automation.log 2>&amp;1</string></array>
  <key>StartInterval</key><integer>3600</integer>
</dict>
</plist>
EOF
launchctl unload "$AGENTS/com.etsy-engine.pinspread.plist" 2>/dev/null || true
launchctl load "$AGENTS/com.etsy-engine.pinspread.plist"
echo "loaded com.etsy-engine.pinspread"

echo "done. logs: $REPO/data/logs/automation.log"
