#!/bin/bash
# PostgreSQL dump for VN Script Studio (docker exec vnss-postgres).
# Cron example:  0 3 * * * /opt/vn-script-studio/scripts/ops/backup_pg.sh
set -euo pipefail

DIR="${BACKUP_DIR:-/opt/vn-script-studio/backups}"
KEEP="${BACKUP_KEEP:-14}"
CONTAINER="${POSTGRES_CONTAINER:-vnss-postgres}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="$DIR/vnss-$STAMP.dump"

mkdir -p "$DIR"
docker exec "$CONTAINER" pg_dump -U vnss -d vnss -Fc -Z 6 > "$OUT"
echo "backup ok $OUT ($(wc -c < "$OUT") bytes)"

# Keep the newest $KEEP files.
mapfile -t old < <(ls -1t "$DIR"/vnss-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))")
if ((${#old[@]})); then
  rm -f "${old[@]}"
  echo "pruned ${#old[@]} old dump(s)"
fi
