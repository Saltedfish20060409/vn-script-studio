#!/bin/bash
# Idempotent crontab for VNSS backup + health probe.
set -euo pipefail
ROOT="${1:-/opt/vn-script-studio}"
BACKUP="$ROOT/scripts/ops/backup_pg.sh"
UPTIME="$ROOT/scripts/ops/uptime_watch.sh"
chmod +x "$BACKUP" "$UPTIME" 2>/dev/null || true
mkdir -p "$ROOT/backups"
touch /var/log/vnss-backup.log /var/log/vnss-uptime.log

TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'scripts/ops/backup_pg.sh' | grep -v 'scripts/ops/uptime_watch.sh' > "$TMP" || true
{
  echo "0 3 * * * $BACKUP >> /var/log/vnss-backup.log 2>&1"
  echo "*/5 * * * * $UPTIME >> /var/log/vnss-uptime.log 2>&1"
} >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "cron installed"
crontab -l | grep scripts/ops || true
