#!/bin/bash
# Zero-downtime deployment script for CampusPoll
# Usage: ./deploy/zero_downtime_deploy.sh

set -e
APP_DIR="/var/www/campuspoll"
VENV="$APP_DIR/venv"
LOG="$APP_DIR/logs/deploy.log"
mkdir -p "$(dirname $LOG)"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

log "=== Starting zero-downtime deployment ==="

# 1. Pull latest code
log "Pulling latest code..."
cd "$APP_DIR" && git pull origin main

# 2. Install/update dependencies in venv
log "Updating dependencies..."
"$VENV/bin/pip" install -r requirements.txt --quiet

# 3. Run DB migrations
log "Running database migrations..."
"$VENV/bin/flask" db upgrade

# 4. Run tests (abort if they fail)
log "Running tests..."
"$VENV/bin/pytest" tests/ -q --tb=short || { log "TESTS FAILED — aborting deploy"; exit 1; }

# 5. Reload Gunicorn (no downtime — sends SIGHUP)
log "Reloading Gunicorn (zero downtime)..."
sudo systemctl reload campuspoll

# 6. Restart Celery worker + beat
log "Restarting Celery services..."
sudo systemctl restart campuspoll-celery campuspoll-beat

# 7. Health check
sleep 3
log "Running health check..."
STATUS=$(curl -sf http://localhost:5000/health | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "error")
if [ "$STATUS" != "ok" ]; then
    log "Health check failed (status=$STATUS) — rolling back..."
    git stash
    "$VENV/bin/flask" db downgrade
    sudo systemctl reload campuspoll
    log "Rollback complete"
    exit 1
fi

log "=== Deployment successful (status=$STATUS) ==="
