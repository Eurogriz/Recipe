#!/usr/bin/env bash
# Thin wrapper around `formulation-backup backup`.
#
# Usage:
#   FW_DATABASE_URL=... ./scripts/ops/backup.sh [output-dir]
#
# The wrapper is intended for cron / systemd timers.  It:
#   - fails on any non-zero exit code (`set -euo pipefail`);
#   - logs to /var/log/formulation-workbench/backup.log by default;
#   - prunes archives older than $FW_BACKUP_RETENTION_DAYS (default 30).
set -euo pipefail

OUTPUT_DIR="${1:-${FW_BACKUP_DIR:-/var/backups/formulation-workbench}}"
LOG_FILE="${FW_BACKUP_LOG:-/var/log/formulation-workbench/backup.log}"
RETENTION_DAYS="${FW_BACKUP_RETENTION_DAYS:-30}"

mkdir -p "$OUTPUT_DIR" "$(dirname "$LOG_FILE")"

echo "[$(date -u --iso-8601=seconds)] backup starting → $OUTPUT_DIR" >> "$LOG_FILE"
archive="$(formulation-backup backup --output-dir "$OUTPUT_DIR")"
echo "[$(date -u --iso-8601=seconds)] backup produced $archive" >> "$LOG_FILE"

# Prune old backups.
find "$OUTPUT_DIR" -type f \( -name "*.db.gz" -o -name "*.db" -o -name "*.sha256" \) \
    -mtime "+${RETENTION_DAYS}" -print -delete >> "$LOG_FILE" 2>&1 || true

echo "[$(date -u --iso-8601=seconds)] backup done" >> "$LOG_FILE"
