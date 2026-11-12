#!/usr/bin/env bash
# Installs AE Link for the current user (macOS). No sudo needed.
#
#   core/aelink_core.py, core/aelink_watch.py
#       -> ~/Library/Application Support/AE Link/
#   resolve_scripts/*.py
#       -> ~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/
#   LaunchAgent that runs the watcher every 30 s
#       -> ~/Library/LaunchAgents/com.riffraff4469.aelink.plist
#
# Re-running it upgrades in place. If an installed file differs from the one
# being copied, the old copy is kept next to it as <name>.bak.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "AE Link only runs on macOS." >&2
    exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_DIR="$HOME/Library/Application Support/AE Link"
RESOLVE_DIR="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
AGENT_DIR="$HOME/Library/LaunchAgents"
LABEL="com.riffraff4469.aelink"
PLIST="$AGENT_DIR/$LABEL.plist"

# Same interpreter the watcher was developed against; fall back to whatever
# python3 is on PATH.
PYTHON="/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON" ]]; then
    echo "python3 not found. Install Python 3 from python.org and run this again." >&2
    exit 1
fi

install_file() {  # install_file <src> <dest path>
    local src="$1" dest="$2"
    if [[ -f "$dest" ]] && ! cmp -s "$src" "$dest"; then
        cp -p "$dest" "$dest.bak"
        echo "  kept previous copy: $dest.bak"
    fi
    cp "$src" "$dest"
    echo "  $dest"
}

echo "Installing AE Link"
mkdir -p "$CORE_DIR" "$RESOLVE_DIR" "$AGENT_DIR"

install_file "$HERE/core/aelink_core.py" "$CORE_DIR/aelink_core.py"
install_file "$HERE/core/aelink_watch.py" "$CORE_DIR/aelink_watch.py"
install_file "$HERE/resolve_scripts/AE Link - Send to After Effects.py" \
             "$RESOLVE_DIR/AE Link - Send to After Effects.py"
install_file "$HERE/resolve_scripts/AE Link - Sync Now.py" \
             "$RESOLVE_DIR/AE Link - Sync Now.py"

TMP_PLIST="$(mktemp)"
cat > "$TMP_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PYTHON</string><string>$CORE_DIR/aelink_watch.py</string>
  </array>
  <key>StartInterval</key><integer>30</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$CORE_DIR/watch.err.log</string>
</dict></plist>
EOF
install_file "$TMP_PLIST" "$PLIST"
rm -f "$TMP_PLIST"

# (Re)load the watcher for this login session.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

cat <<EOF

Done. Next:
  1. In Resolve: Preferences > System > General > External scripting using: Local
     (the background watcher needs it).
  2. Restart Resolve. The scripts appear under Workspace > Scripts.
Watcher Python: $PYTHON
Log: $CORE_DIR/aelink.log
EOF
