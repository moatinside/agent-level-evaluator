#!/bin/bash
##############################################################################
# Canary Rollback Script - Emergency rollback from Canary deployment
##############################################################################

set -e

CANARY_LOG_DIR="${CANARY_LOG_DIR:-/tmp/canary-deploy}"
DEPLOYMENT_INFO="$CANARY_LOG_DIR/deployment_info.json"

if [ ! -f "$DEPLOYMENT_INFO" ]; then
  echo "❌ Deployment info not found: $DEPLOYMENT_INFO"
  exit 1
fi

echo "============================================================================"
echo "🔄 Canary Deployment Rollback"
echo "============================================================================"
echo ""

# Extract deployment info
OLD_PID=$(jq -r '.old_pid' "$DEPLOYMENT_INFO")
NEW_PID=$(jq -r '.new_pid' "$DEPLOYMENT_INFO")
OLD_COMMIT=$(jq -r '.old_version' "$DEPLOYMENT_INFO")
ORIGINAL_COMMIT=$(jq -r '.original_commit' "$DEPLOYMENT_INFO")
REPO_DIR="$(cd "$CANARY_LOG_DIR/../.." && pwd)"

echo "📋 Rollback Plan:"
echo "   1. Kill new version (canary) PID $NEW_PID"
echo "   2. Keep old version (stable) PID $OLD_PID running"
echo "   3. Restore original git state: $ORIGINAL_COMMIT"
echo "   4. Archive canary logs"
echo ""

# Step 1: Kill new version
echo "📌 Step 1: Stopping new version (canary)..."
if kill $NEW_PID 2>/dev/null; then
  echo "   ✅ Killed PID $NEW_PID"
else
  echo "   ⚠️  PID $NEW_PID already stopped"
fi
sleep 1

# Step 2: Verify old version is still running
echo ""
echo "📌 Step 2: Verifying old version is still healthy..."
if curl -s http://127.0.0.1:8000/health > /dev/null 2>&1; then
  echo "   ✅ Old version still healthy on port 8000"
else
  echo "   ❌ Old version is not responding!"
  echo "   Manual intervention required. Old version PID: $OLD_PID"
  exit 1
fi

# Step 3: Restore git state
echo ""
echo "📌 Step 3: Restoring original git state..."
cd "$REPO_DIR"
git checkout "$ORIGINAL_COMMIT" > /dev/null 2>&1
echo "   ✅ Restored: $ORIGINAL_COMMIT"

# Step 4: Archive logs
echo ""
echo "📌 Step 4: Archiving canary logs..."
ARCHIVE_DIR="$CANARY_LOG_DIR/archive_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$ARCHIVE_DIR"
cp "$CANARY_LOG_DIR"/*.log "$ARCHIVE_DIR/" 2>/dev/null || true
cp "$DEPLOYMENT_INFO" "$ARCHIVE_DIR/" 2>/dev/null || true
echo "   ✅ Logs archived to: $ARCHIVE_DIR"

# Step 5: Cleanup
echo ""
echo "📌 Step 5: Cleanup..."
rm -f "$DEPLOYMENT_INFO" "$CANARY_LOG_DIR/nginx_canary.conf"
echo "   ✅ Deployment metadata cleared"

echo ""
echo "============================================================================"
echo "✅ Rollback Complete"
echo "============================================================================"
echo ""
echo "📊 Current Status:"
echo "   Old version (stable): PID $OLD_PID on port 8000 ✅"
echo "   New version (canary): STOPPED ❌"
echo "   Git state: $ORIGINAL_COMMIT"
echo ""
echo "📝 Next Steps:"
echo "   1. Analyze failure: less $ARCHIVE_DIR/new_version.log"
echo "   2. Fix issues in code"
echo "   3. Re-run canary: bash $REPO_DIR/scripts/canary_deploy.sh"
echo ""
