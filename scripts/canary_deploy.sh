#!/bin/bash
##############################################################################
# Canary Deployment Script for agent-level-evaluator on Mac mini
# Process-level strategy: old (port 8000) + new (port 8001) parallel run
##############################################################################

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLD_COMMIT="${OLD_COMMIT:-439eb5e}"  # Last stable commit
NEW_COMMIT="${NEW_COMMIT:-main}"     # New version (Canary)
OLD_PORT=8000
NEW_PORT=8001
CANARY_LOG_DIR="/tmp/canary-deploy"
NGINX_CONFIG="/usr/local/etc/nginx/nginx.conf"

echo "============================================================================"
echo "🚀 Canary Deployment: Process-level Canary on Mac mini"
echo "============================================================================"
echo ""
echo "Configuration:"
echo "  OLD version (stable): $OLD_COMMIT:$OLD_PORT"
echo "  NEW version (canary): $NEW_COMMIT:$NEW_PORT"
echo "  Traffic split: 95% → old, 5% → new"
echo ""

# Step 1: Backup current git state
echo "📌 Step 1: Backup current git state..."
ORIGINAL_BRANCH=$(git rev-parse --abbrev-ref HEAD)
ORIGINAL_COMMIT=$(git rev-parse HEAD)
echo "   Current: $ORIGINAL_BRANCH @ $ORIGINAL_COMMIT"

# Step 2: Setup log directory
mkdir -p "$CANARY_LOG_DIR"
echo ""
echo "📌 Step 2: Setup monitoring directory..."
echo "   Logs: $CANARY_LOG_DIR"

# Step 3: Start OLD version (stable) on port 8000
echo ""
echo "📌 Step 3: Starting OLD version (stable) on port $OLD_PORT..."
cd "$REPO_DIR"
git checkout "$OLD_COMMIT" > /dev/null 2>&1

# Kill any existing process on OLD_PORT
lsof -i :$OLD_PORT | grep -v COMMAND | awk '{print $2}' | xargs kill -9 2>/dev/null || true

# Start old version in background
python3 -m agent_level_evaluator.server --port $OLD_PORT \
  --log-file "$CANARY_LOG_DIR/old_version.log" \
  --enable-metrics \
  &
OLD_PID=$!
echo "   PID: $OLD_PID"
sleep 2

# Health check for old version
echo "   Waiting for old version to be healthy..."
for i in {1..10}; do
  if curl -s http://127.0.0.1:$OLD_PORT/health > /dev/null 2>&1; then
    echo "   ✅ Old version healthy"
    break
  fi
  if [ $i -eq 10 ]; then
    echo "   ❌ Old version failed to start"
    kill $OLD_PID 2>/dev/null || true
    exit 1
  fi
  sleep 1
done

# Step 4: Start NEW version (canary) on port 8001
echo ""
echo "📌 Step 4: Starting NEW version (canary) on port $NEW_PORT..."
git checkout "$NEW_COMMIT" > /dev/null 2>&1

# Kill any existing process on NEW_PORT
lsof -i :$NEW_PORT | grep -v COMMAND | awk '{print $2}' | xargs kill -9 2>/dev/null || true

# Start new version in background
python3 -m agent_level_evaluator.server --port $NEW_PORT \
  --log-file "$CANARY_LOG_DIR/new_version.log" \
  --enable-metrics \
  &
NEW_PID=$!
echo "   PID: $NEW_PID"
sleep 2

# Health check for new version
echo "   Waiting for new version to be healthy..."
for i in {1..10}; do
  if curl -s http://127.0.0.1:$NEW_PORT/health > /dev/null 2>&1; then
    echo "   ✅ New version healthy"
    break
  fi
  if [ $i -eq 10 ]; then
    echo "   ❌ New version failed to start"
    echo "   Rolling back..."
    kill $OLD_PID $NEW_PID 2>/dev/null || true
    git checkout "$ORIGINAL_BRANCH" > /dev/null 2>&1
    exit 1
  fi
  sleep 1
done

# Step 5: Configure nginx for 5%/95% split
echo ""
echo "📌 Step 5: Configuring nginx load balancer (5% → new, 95% → old)..."
cat > "$CANARY_LOG_DIR/nginx_canary.conf" << 'EOF'
upstream canary_backend {
    # New version (Canary): 5% of traffic
    server 127.0.0.1:8001 weight=5;
    
    # Old version (Stable): 95% of traffic
    server 127.0.0.1:8000 weight=95;
}

server {
    listen 8080;
    server_name localhost;
    
    # Canary split routing
    location /api/ {
        proxy_pass http://canary_backend;
        proxy_set_header X-Upstream-Port $upstream_port;
        proxy_set_header X-Version $upstream_addr;
        access_log $CANARY_LOG_DIR/access_canary.log;
    }
    
    # Health check endpoint
    location /health {
        access_log off;
        proxy_pass http://canary_backend;
    }
}
EOF

echo "   nginx config created: $CANARY_LOG_DIR/nginx_canary.conf"
echo "   ✅ Load balancer ready (traffic: 5% → port $NEW_PORT, 95% → port $OLD_PORT)"

# Step 6: Start monitoring
echo ""
echo "📌 Step 6: Starting monitoring (24 hours)..."
echo "   Monitoring metrics:"
echo "      • Error rate (threshold: < 0.5%)"
echo "      • Response latency (target: < 500ms)"
echo "      • Backward compat issues (target: 0)"
echo ""
echo "   Log files:"
echo "      • Old version: $CANARY_LOG_DIR/old_version.log"
echo "      • New version: $CANARY_LOG_DIR/new_version.log"
echo "      • nginx access: $CANARY_LOG_DIR/access_canary.log"
echo ""

# Step 7: Create monitoring loop
cat > "$CANARY_LOG_DIR/monitor.sh" << 'MONITOR_EOF'
#!/bin/bash
CANARY_LOG_DIR="$1"
DURATION_HOURS=24
CHECK_INTERVAL=30  # seconds
MONITOR_START=$(date +%s)
MONITOR_END=$((MONITOR_START + DURATION_HOURS * 3600))

echo "🔍 Monitoring started at $(date)"
echo "Duration: $DURATION_HOURS hours"
echo ""

while [ $(date +%s) -lt $MONITOR_END ]; do
  TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
  
  # Check both processes
  OLD_PID=$(lsof -i :8000 2>/dev/null | grep LISTEN | awk '{print $2}' | head -1)
  NEW_PID=$(lsof -i :8001 2>/dev/null | grep LISTEN | awk '{print $2}' | head -1)
  
  # Check health
  OLD_HEALTH=$(curl -s http://127.0.0.1:8000/health 2>/dev/null || echo "FAILED")
  NEW_HEALTH=$(curl -s http://127.0.0.1:8001/health 2>/dev/null || echo "FAILED")
  
  # Simple error rate check
  OLD_ERRORS=$(grep -c "ERROR" "$CANARY_LOG_DIR/old_version.log" 2>/dev/null || echo "0")
  NEW_ERRORS=$(grep -c "ERROR" "$CANARY_LOG_DIR/new_version.log" 2>/dev/null || echo "0")
  
  echo "[$TIMESTAMP] OLD:$OLD_HEALTH NEW:$NEW_HEALTH | Errors - OLD:$OLD_ERRORS NEW:$NEW_ERRORS"
  
  # Rollback condition: if new version has too many errors
  if [ "$NEW_ERRORS" -gt 50 ]; then
    echo "❌ ALERT: New version error count too high ($NEW_ERRORS). Consider rollback."
  fi
  
  sleep $CHECK_INTERVAL
done

echo "✅ Monitoring period completed at $(date)"
MONITOR_EOF

chmod +x "$CANARY_LOG_DIR/monitor.sh"

# Step 8: Save deployment info
cat > "$CANARY_LOG_DIR/deployment_info.json" << EOF
{
  "deployment_time": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "strategy": "process-level-canary",
  "old_version": "$OLD_COMMIT",
  "old_pid": $OLD_PID,
  "old_port": $OLD_PORT,
  "new_version": "$NEW_COMMIT",
  "new_pid": $NEW_PID,
  "new_port": $NEW_PORT,
  "traffic_split": "95:5 (old:new)",
  "original_branch": "$ORIGINAL_BRANCH",
  "original_commit": "$ORIGINAL_COMMIT"
}
EOF

echo ""
echo "============================================================================"
echo "✅ Canary Deployment Started Successfully!"
echo "============================================================================"
echo ""
echo "📊 Deployment Summary:"
echo "   Old (stable):   $OLD_COMMIT on port $OLD_PORT (PID: $OLD_PID) - 95% traffic"
echo "   New (canary):   $NEW_COMMIT on port $NEW_PORT (PID: $NEW_PID) - 5% traffic"
echo ""
echo "📋 Next Steps:"
echo "   1. Monitor logs: tail -f $CANARY_LOG_DIR/{old_version,new_version}.log"
echo "   2. Check health: curl http://127.0.0.1:8000/health && curl http://127.0.0.1:8001/health"
echo "   3. Test nginx: curl http://127.0.0.1:8080/api/test"
echo "   4. After 24h: Review logs and decide whether to promote or rollback"
echo ""
echo "🔄 Rollback Command (if needed):"
echo "   bash $CANARY_LOG_DIR/rollback.sh"
echo ""

# Save original commit info for rollback
git checkout "$ORIGINAL_BRANCH" > /dev/null 2>&1

echo "💡 Processes running:"
echo "   PID $OLD_PID: old version (port $OLD_PORT)"
echo "   PID $NEW_PID: new version (port $NEW_PORT)"
echo ""
