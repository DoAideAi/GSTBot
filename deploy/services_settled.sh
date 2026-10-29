#!/usr/bin/env bash
# Prove the services a release just restarted are still running, not merely
# started. Called by deploy.sh after the health checks:
#
#   deploy/services_settled.sh gstbot-api.service gstbot-worker.service ...
#
# The units are Type=exec with Restart=always, so `systemctl restart` succeeds
# the moment each process has been exec'd. A worker or beat that then dies (an
# import error in a task module, a setting only Celery reads) is restarted every
# RestartSec and reads "active" between deaths. The checks before this one ask
# the API, the static site and the edge, none of which notices, so a release
# was declared deployed while uploads queued and never parsed.
#
# Two checks, because the two Celery processes differ:
#   * a worker answers a ping, which /health/jobs reports. One that dies on
#     import never does.
#   * beat answers nothing, so its crash loop shows only as restarts. Each
#     unit's NRestarts counts systemd's automatic restarts since this release
#     started it, and any at all means it fell over.
set -euo pipefail

JOBS_URL="${GSTBOT_JOBS_URL:-http://172.18.0.1:3008/api/v1/health/jobs}"
# Long enough for a process that dies on start to have died and been restarted
# at least once (RestartSec=5), counted from when this is called.
SETTLE_SECONDS="${GSTBOT_SETTLE_SECONDS:-12}"
WORKER_WAIT_SECONDS="${GSTBOT_WORKER_WAIT_SECONDS:-45}"

[ "$#" -gt 0 ] || { echo "usage: $0 UNIT..." >&2; exit 2; }

# ---- A worker answers -----------------------------------------------------
worker_state() {
    # "up", "down", or "off" when Celery is disabled and no worker is expected.
    curl -fsS --max-time 5 "$JOBS_URL" 2>/dev/null | python3 -c '
import json, sys
try:
    doc = json.load(sys.stdin)
except ValueError:
    print("down"); sys.exit()
workers = doc.get("workers") if isinstance(doc.get("workers"), dict) else {}
if not doc.get("celery_enabled", True):
    print("off")
else:
    print("up" if workers.get("reachable") else "down")
' 2>/dev/null || echo down
}

answered=""
for attempt in $(seq 1 "$WORKER_WAIT_SECONDS"); do
    state="$(worker_state)"
    if [ "$state" = up ] || [ "$state" = off ]; then
        answered="$state"
        [ "$state" = up ] && echo "A Celery worker answered after ${attempt}s"
        break
    fi
    sleep 1
done
if [ -z "$answered" ]; then
    echo "no Celery worker answered a ping within ${WORKER_WAIT_SECONDS}s; journalctl -u gstbot-worker -n 100" >&2
    exit 1
fi

# ---- Nothing has had to be restarted --------------------------------------
sleep "$SETTLE_SECONDS"
failed=0
for unit in "$@"; do
    active="$(systemctl show --property=ActiveState --value "$unit" 2>/dev/null || true)"
    restarts="$(systemctl show --property=NRestarts --value "$unit" 2>/dev/null || true)"
    if [ "$active" != active ]; then
        echo "$unit is ${active:-unreadable}, not active; journalctl -u ${unit%.service} -n 100" >&2
        failed=1
    elif [ -n "$restarts" ] && [ "$restarts" != 0 ]; then
        echo "$unit has been restarted by systemd $restarts time(s) since this release started it; journalctl -u ${unit%.service} -n 100" >&2
        failed=1
    fi
done
[ "$failed" -eq 0 ] && echo "Every service is still up ${SETTLE_SECONDS}s after the restart"
exit "$failed"
