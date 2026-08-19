#!/bin/bash
# Hit the public health URL. Non-zero exit if down (cron can mail / log).
set -euo pipefail
URL="${VNSS_HEALTH_URL:-https://studio.nexesr.top/health}"
LOG="${VNSS_UPTIME_LOG:-/var/log/vnss-uptime.log}"
if curl -fsS --max-time 8 "$URL" >/dev/null; then
  exit 0
fi
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) FAIL $URL" >> "$LOG"
exit 1
