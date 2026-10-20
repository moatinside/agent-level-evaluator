#!/bin/bash
##############################################################################
# Blue-Green Deployment for agent-level-evaluator
# Two versions run independently; switch with launchctl
##############################################################################

set -e

REPO_DIR="/Users/yokapro/Developer/agent-level-evaluator-upstream"
BLUE_DIR="/opt/agent-level-evaluator/blue"
GREEN_DIR="/opt/agent-level-evaluator/green"
LOG_DIR="/var/log/agent-level-evaluator"

BLUE_PLIST="$HOME/Library/LaunchAgents/com.local.agent-level-evaluator.blue.plist"
GREEN_PLIST="$HOME/Library/LaunchAgents/com.local.agent-level-evaluator.green.plist"

echo "============================================================================"
echo "🔵🟢 Blue-Green Deployment Setup"
echo "============================================================================"
echo ""

# Step 1: Create directory structure
echo "📌 Step 1: Create Blue-Green directory structure..."
mkdir -p "$BLUE_DIR" "$GREEN_DIR" "$LOG_DIR"

# Step 2: Deploy Blue version (current stable)
echo ""
echo "📌 Step 2: Deploy Blue version (current stable)..."
cp -r "$REPO_DIR" "$BLUE_DIR/repo"
cd "$BLUE_DIR"
python3 -m venv blue_venv
source blue_venv/bin/activate
pip install -q --upgrade pip
if [ -f "$BLUE_DIR/repo/requirements.txt" ]; then
  pip install -q -r "$BLUE_DIR/repo/requirements.txt"
fi

# Create run script for Blue
cat > "$BLUE_DIR/run.sh" << 'EOF'
#!/bin/bash
REPO_DIR="/opt/agent-level-evaluator/blue/repo"
LOG_DIR="/var/log/agent-level-evaluator"
VENV_DIR="/opt/agent-level-evaluator/blue/blue_venv"

source "$VENV_DIR/bin/activate"
cd "$REPO_DIR"

exec python3 -m evals.run_evals \
  --log-file "$LOG_DIR/blue_evaluator.log" \
  --metrics-port 9090 \
  --version blue \
  --keep-running
EOF

chmod +x "$BLUE_DIR/run.sh"
echo "   ✅ Blue version deployed"

# Step 3: Deploy Green version (candidate)
echo ""
echo "📌 Step 3: Deploy Green version (candidate)..."
cp -r "$REPO_DIR" "$GREEN_DIR/repo"
cd "$GREEN_DIR"
python3 -m venv green_venv
source green_venv/bin/activate
pip install -q --upgrade pip
if [ -f "$GREEN_DIR/repo/requirements.txt" ]; then
  pip install -q -r "$GREEN_DIR/repo/requirements.txt"
fi

# Create run script for Green
cat > "$GREEN_DIR/run.sh" << 'EOF'
#!/bin/bash
REPO_DIR="/opt/agent-level-evaluator/green/repo"
LOG_DIR="/var/log/agent-level-evaluator"
VENV_DIR="/opt/agent-level-evaluator/green/green_venv"

source "$VENV_DIR/bin/activate"
cd "$REPO_DIR"

exec python3 -m evals.run_evals \
  --log-file "$LOG_DIR/green_evaluator.log" \
  --metrics-port 9091 \
  --version green \
  --keep-running
EOF

chmod +x "$GREEN_DIR/run.sh"
echo "   ✅ Green version deployed"

# Step 4: Create Blue plist
echo ""
echo "📌 Step 4: Create Blue launchd plist..."
cat > "$BLUE_PLIST" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.agent-level-evaluator.blue</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/agent-level-evaluator/blue/run.sh</string>
    </array>
    <key>StandardOutPath</key>
    <string>/var/log/agent-level-evaluator/blue_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/agent-level-evaluator/blue_stderr.log</string>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST

echo "   ✅ Blue plist created"

# Step 5: Create Green plist
echo ""
echo "📌 Step 5: Create Green launchd plist..."
cat > "$GREEN_PLIST" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.agent-level-evaluator.green</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/agent-level-evaluator/green/run.sh</string>
    </array>
    <key>StandardOutPath</key>
    <string>/var/log/agent-level-evaluator/green_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/agent-level-evaluator/green_stderr.log</string>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST

echo "   ✅ Green plist created"

# Step 6: Load Blue (initial active version)
echo ""
echo "📌 Step 6: Start Blue version (initial active)..."
launchctl load "$BLUE_PLIST" 2>/dev/null || true
sleep 2
echo "   ✅ Blue started"

echo ""
echo "============================================================================"
echo "✅ Blue-Green Setup Complete!"
echo "============================================================================"
echo ""
echo "📊 Deployment Status:"
echo "   🔵 Blue (current active):  /opt/agent-level-evaluator/blue"
echo "   🟢 Green (standby):        /opt/agent-level-evaluator/green"
echo ""
echo "📋 Commands:"
echo "   Check status:   launchctl list | grep agent-level"
echo "   Blue logs:      tail -f $LOG_DIR/blue_evaluator.log"
echo "   Green logs:     tail -f $LOG_DIR/green_evaluator.log"
echo ""
echo "🔄 Switch to Green:"
echo "   launchctl unload \"$BLUE_PLIST\""
echo "   launchctl load \"$GREEN_PLIST\""
echo ""
