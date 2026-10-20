#!/bin/bash
##############################################################################
# Setup: agent-level-evaluator as macOS systemd (launchd) service
# Strategy: Deploy as background service with Blue-Green switching capability
##############################################################################

set -e

REPO_DIR="/Users/yokapro/Developer/agent-level-evaluator-upstream"
SERVICE_USER="yokapro"
WORKING_DIR="/opt/agent-level-evaluator"
VENV_DIR="$WORKING_DIR/venv"
LOG_DIR="/var/log/agent-level-evaluator"

echo "============================================================================"
echo "🚀 Setup: agent-level-evaluator as macOS Service (Blue-Green Ready)"
echo "============================================================================"
echo ""

# Step 1: Create working directory
echo "📌 Step 1: Create working directory..."
sudo mkdir -p "$WORKING_DIR" "$LOG_DIR"
sudo chown -R "$SERVICE_USER:staff" "$WORKING_DIR" "$LOG_DIR"
mkdir -p "$WORKING_DIR"

# Step 2: Copy repository to working directory
echo ""
echo "📌 Step 2: Copy repository..."
cp -r "$REPO_DIR" "$WORKING_DIR/repo"

# Step 3: Create Python virtual environment
echo ""
echo "📌 Step 3: Setup Python virtual environment..."
cd "$WORKING_DIR"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install -q --upgrade pip

# Step 4: Install dependencies
echo ""
echo "📌 Step 4: Install dependencies..."
if [ -f "$WORKING_DIR/repo/requirements.txt" ]; then
  pip install -q -r "$WORKING_DIR/repo/requirements.txt"
else
  echo "   ⚠️  requirements.txt not found, skipping pip install"
fi

# Step 5: Create service wrapper script
echo ""
echo "📌 Step 5: Create service wrapper script..."
cat > "$WORKING_DIR/run.sh" << 'EOF'
#!/bin/bash
# Service wrapper: restart logic + logging

REPO_DIR="/opt/agent-level-evaluator/repo"
LOG_DIR="/var/log/agent-level-evaluator"
VENV_DIR="/opt/agent-level-evaluator/venv"

source "$VENV_DIR/bin/activate"

cd "$REPO_DIR"

# Run with output logging
exec python3 -m evals.run_evals \
  --log-file "$LOG_DIR/evaluator.log" \
  --metrics-port 9090 \
  --keep-running
EOF

chmod +x "$WORKING_DIR/run.sh"
echo "   ✅ Service wrapper created: $WORKING_DIR/run.sh"

# Step 6: Create launchd plist (macOS service)
echo ""
echo "📌 Step 6: Create launchd service definition..."
PLIST_FILE="$HOME/Library/LaunchAgents/com.local.agent-level-evaluator.plist"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_FILE" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.agent-level-evaluator</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>/opt/agent-level-evaluator/run.sh</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>/opt/agent-level-evaluator</string>
    
    <key>StandardOutPath</key>
    <string>/var/log/agent-level-evaluator/stdout.log</string>
    
    <key>StandardErrorPath</key>
    <string>/var/log/agent-level-evaluator/stderr.log</string>
    
    <key>KeepAlive</key>
    <true/>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>StartInterval</key>
    <integer>3600</integer>
</dict>
</plist>
EOF

chmod 644 "$PLIST_FILE"
echo "   ✅ Plist created: $PLIST_FILE"

# Step 7: Load service
echo ""
echo "📌 Step 7: Load launchd service..."
launchctl load "$PLIST_FILE" 2>/dev/null || launchctl unload "$PLIST_FILE" && launchctl load "$PLIST_FILE"
sleep 2

# Step 8: Verify service
echo ""
echo "📌 Step 8: Verify service status..."
if launchctl list | grep -q "com.local.agent-level-evaluator"; then
  echo "   ✅ Service loaded successfully"
else
  echo "   ❌ Service failed to load"
  exit 1
fi

# Step 9: Create version file
echo ""
echo "📌 Step 9: Record deployment info..."
cat > "$WORKING_DIR/deployment_info.json" << 'EOF'
{
  "service_name": "com.local.agent-level-evaluator",
  "working_dir": "/opt/agent-level-evaluator",
  "log_dir": "/var/log/agent-level-evaluator",
  "plist_path": "~/Library/LaunchAgents/com.local.agent-level-evaluator.plist",
  "deployment_time": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "version": "1.0.0-production"
}
EOF

echo ""
echo "============================================================================"
echo "✅ Service Setup Complete!"
echo "============================================================================"
echo ""
echo "📊 Service Info:"
echo "   Service name: com.local.agent-level-evaluator"
echo "   Working dir: $WORKING_DIR"
echo "   Log file: $LOG_DIR/evaluator.log"
echo "   Plist: $PLIST_FILE"
echo ""
echo "📋 Next Steps:"
echo "   1. Check logs: tail -f $LOG_DIR/evaluator.log"
echo "   2. Service status: launchctl list | grep agent-level"
echo "   3. Stop service: launchctl unload \"$PLIST_FILE\""
echo "   4. Restart: launchctl reload \"$PLIST_FILE\""
echo ""
