#!/bin/bash
# CampusPoll database backup script
# Add to crontab: 0 2 * * * /var/www/campuspoll/deploy/backup.sh

set -e
BACKUP_DIR="/var/backups/campuspoll"
DATE=$(date +%Y%m%d_%H%M%S)
APP_DIR="/var/www/campuspoll"
KEEP_DAYS=30

mkdir -p "$BACKUP_DIR"

# Load env
set -a
source "$APP_DIR/.env"
set +a

if [[ "$DATABASE_URL" == *"postgresql"* ]]; then
    DB_NAME=$(echo "$DATABASE_URL" | sed 's/.*\///')
    pg_dump "$DATABASE_URL" | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"
    echo "PostgreSQL backup: $BACKUP_DIR/db_$DATE.sql.gz"
else
    DB_FILE="$APP_DIR/instance/campuspoll.db"
    if [ -f "$DB_FILE" ]; then
        cp "$DB_FILE" "$BACKUP_DIR/db_$DATE.sqlite"
        gzip "$BACKUP_DIR/db_$DATE.sqlite"
        echo "SQLite backup: $BACKUP_DIR/db_$DATE.sqlite.gz"
    fi
fi

# Backup uploads
tar -czf "$BACKUP_DIR/uploads_$DATE.tar.gz" -C "$APP_DIR/static" images/ 2>/dev/null || true

# Remove old backups
find "$BACKUP_DIR" -name "db_*" -mtime +$KEEP_DAYS -delete
find "$BACKUP_DIR" -name "uploads_*" -mtime +$KEEP_DAYS -delete

echo "Backup complete: $DATE"
