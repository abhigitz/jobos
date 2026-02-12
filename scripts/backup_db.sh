#!/bin/bash
# JobOS Database Backup Script
# Run: ./scripts/backup_db.sh

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="jobos_backup_${TIMESTAMP}.sql"

echo "Starting backup..."
/opt/homebrew/opt/postgresql@17/bin/pg_dump $DATABASE_URL > $BACKUP_FILE
gzip $BACKUP_FILE
echo "Backup complete: ${BACKUP_FILE}.gz"
