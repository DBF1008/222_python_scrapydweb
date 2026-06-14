#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# launch-scrapyd.sh — Start Scrapyd with basic auth and wait until ready
#
# Writes ~/scrapyd.conf with username=admin, password=12345
# Launches scrapyd as background process via nohup
# Polls http://127.0.0.1:6800/daemonstatus.json until responsive (max 30s)
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRAPYD_CONF="${HOME}/scrapyd.conf"
SCRAPYD_LOG="${HOME}/scrapyd.log"
MAX_WAIT=30

echo "=========================================="
echo "  Writing Scrapyd config"
echo "=========================================="
cat > "$SCRAPYD_CONF" <<EOF
[scrapyd]
username = admin
password = 12345
EOF
cat "$SCRAPYD_CONF"

echo ""
echo "=========================================="
echo "  Launching Scrapyd"
echo "=========================================="
nohup scrapyd > "$SCRAPYD_LOG" 2>&1 &
SCRAPYD_PID=$!
echo "Scrapyd PID: ${SCRAPYD_PID}"

echo ""
echo "Waiting for Scrapyd to be ready (max ${MAX_WAIT}s)..."
WAITED=0
until curl -s -u admin:12345 http://127.0.0.1:6800/daemonstatus.json > /dev/null 2>&1; do
  WAITED=$((WAITED + 1))
  if [ "$WAITED" -ge "$MAX_WAIT" ]; then
    echo ""
    echo "::error::Scrapyd did not start within ${MAX_WAIT}s"
    echo "=== Scrapyd log ==="
    cat "$SCRAPYD_LOG"
    exit 1
  fi
  sleep 1
done

echo "Scrapyd is ready (took ${WAITED}s)"
echo ""
echo "=== Scrapyd log ==="
cat "$SCRAPYD_LOG"
