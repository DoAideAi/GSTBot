#!/usr/bin/env bash
# Check the things nothing else on this box checks, and say so when one of
# them is wrong. Run by gstbot-monitor.timer; safe to run by hand:
#
#   systemctl start gstbot-monitor.service        # exactly what the timer does
#   sudo -u gstbot /opt/GSTBot/deploy/monitor.sh  # same, without the sandbox
#
# systemd already restarts what crashes, and the readiness probe already holds
# traffic back from an API that cannot reach its database. What neither of them
# does is tell anybody. The failures this exists for are the quiet ones:
#
#   * A unit that exhausted StartLimitBurst and stopped being restarted. From
#     the outside that is indistinguishable from a unit nobody started.
#   * gstbot-backup.timer never enabled, or disabled during some maintenance
#     and not put back. The runbook calls this out precisely because there is
#     no other sign of it — the directory simply stops growing.
#   * Dumps that stopped succeeding. The backup unit fails loudly into the
#     journal at 02:30, which is a message with no reader.
#   * The disk filling. It takes out four products, and the first symptom
#     anyone sees is usually the least informative one.
#
# It writes nothing. There is no state directory and no ReadWritePaths in the
# unit, which is what makes "the monitor is broken" a much smaller blast radius
# than the things it watches.
#
# It also does not deduplicate. A problem that persists is reported every time
# the timer fires, deliberately: a monitor that goes quiet after the first
# alert cannot be told apart from one that stopped running, and that is a
# worse failure than a repeated message.
set -euo pipefail

# Same convention as backup.sh: every knob is an environment variable with a
# default, so the unit stays declarative and a check can be pointed somewhere
# else for a drill without editing this file.
BACKUP_DIR="${GSTBOT_BACKUP_DIR:-/var/backups/gstbot}"
# The uploaded invoices backup.sh snapshots, with backup.sh's own default.
UPLOADS="${GSTBOT_UPLOAD_DIR:-${UPLOAD_DIR:-/var/lib/gstbot/invoices}}"
# 48 rather than 24. The timer carries up to 15 minutes of jitter and a box
# that rebooted through 02:30 catches up shortly after boot, so a 24-hour
# window reports a backup that is merely late.
MAX_BACKUP_AGE_HOURS="${GSTBOT_MONITOR_MAX_BACKUP_AGE_HOURS:-48}"
# Enough headroom for tonight's dump plus a release's node_modules. Below this
# the next thing to fail is chosen by whichever product writes first.
MIN_FREE_MB="${GSTBOT_MONITOR_MIN_FREE_MB:-1024}"
# The bridge address, not the public name: this asks whether the API itself is
# serving, with the edge taken out of the question.
READY_URL="${GSTBOT_MONITOR_READY_URL:-http://172.18.0.1:3008/api/v1/health/ready}"
# And this asks the opposite — the whole path a browser takes, including DNS,
# TLS and a Caddy container that belongs to another product. /health/live
# rather than /health/ready, so a degraded dependency is not reported twice.
PUBLIC_URL="${GSTBOT_MONITOR_PUBLIC_URL:-https://gst.doaide.com/api/v1/health/live}"
# Running is not working. A worker can be active while it no longer takes
# tasks, the scheduler active while the deadline sweep stopped firing, Redis
# gone while the API answers ready: all of it passed every check above, since
# both endpoints answer 200 while degraded. Their bodies say what is wrong, and
# monitor_health.py turns them into one problem per line.
JOBS_URL="${GSTBOT_MONITOR_JOBS_URL:-http://172.18.0.1:3008/api/v1/health/jobs}"
HEALTH_URL="${GSTBOT_MONITOR_HEALTH_URL:-http://172.18.0.1:3008/api/v1/health}"
# Tasks waiting before a backlog is reported. A busy hour is a few dozen.
MAX_QUEUE_DEPTH="${GSTBOT_MONITOR_MAX_QUEUE_DEPTH:-100}"
# Optional. Unset, everything below still runs and still lands in the journal
# with a failed unit behind it; set, the same summary reaches somewhere with a
# person attached. See "Monitoring" in deploy/README.md.
WEBHOOK="${GSTBOT_ALERT_WEBHOOK:-}"

# The units that are supposed to be running right now. gstbot-migrate is not
# here: it is a oneshot that stays active after exiting, so "active" says only
# that the last release migrated.
#
# gstbot-beat is the one on this list whose death is otherwise completely
# silent. Nothing queues up behind a stopped scheduler and no request fails —
# the deadline alerts simply stop being raised, and the first sign of it is a
# business being penalised for a return nobody reminded them about.
SERVICES=(gstbot-api.service gstbot-web.service gstbot-worker.service gstbot-beat.service)
# The timer is checked rather than its service. gstbot-backup.service is
# inactive between runs, which is the correct state and not a fact about
# whether backups are happening.
TIMERS=(gstbot-backup.timer)

problems=()
fail() {
    printf 'PROBLEM: %s\n' "$*" >&2
    problems+=("$*")
}
ok() { printf 'ok: %s\n' "$*"; }

# Every check runs even after one has failed. Stopping at the first would
# report a dead API and say nothing about the disk that caused it.

# ---- Units ----------------------------------------------------------------
# `systemctl show` rather than `is-active`, because it distinguishes failed
# from inactive from activating, and the three mean different things at 09:00.
state_of() { systemctl show --property=ActiveState --value "$1" 2>/dev/null || true; }

for unit in "${SERVICES[@]}"; do
    state="$(state_of "$unit")"
    if [ "$state" = active ]; then
        ok "$unit is active"
    else
        fail "$unit is ${state:-unreadable}, expected active"
    fi
done

for unit in "${TIMERS[@]}"; do
    state="$(state_of "$unit")"
    if [ "$state" = active ]; then
        ok "$unit is active"
    else
        # Worth its own wording: an inactive timer is not a crash, it is a
        # step of the runbook that was never run, and it has been silently
        # true since installation.
        fail "$unit is ${state:-unreadable} — nothing is taking backups"
    fi
done

# ---- Backups --------------------------------------------------------------
# That the timer is active says a dump was attempted, not that one was
# written. Only the directory says that.
if [ ! -d "$BACKUP_DIR" ]; then
    fail "$BACKUP_DIR does not exist"
elif [ ! -r "$BACKUP_DIR" ]; then
    fail "$BACKUP_DIR is not readable by $(id -un)"
else
    recent="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.dump' \
        -newermt "-${MAX_BACKUP_AGE_HOURS} hours" -print -quit 2>/dev/null || true)"
    if [ -n "$recent" ]; then
        ok "a dump newer than ${MAX_BACKUP_AGE_HOURS}h exists"
    else
        # The count distinguishes "backups stopped last week" from "backups
        # never started", which are different mornings.
        total="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.dump' 2>/dev/null | wc -l)"
        fail "no dump in $BACKUP_DIR newer than ${MAX_BACKUP_AGE_HOURS}h (${total// /} on disk)"
    fi

    # The snapshot of the uploaded invoices, held to the same window. backup.sh
    # takes it after the dump, so a snapshot that fails every night still
    # leaves a fresh dump behind, and the check above stays green while the
    # scans themselves stop being kept. Finished snapshots only: a name that
    # still ends in .partial is an rsync that never completed. None is expected
    # where there is no upload directory, because backup.sh takes none there.
    if [ -d "$UPLOADS" ]; then
        snapshot="$(find "$BACKUP_DIR" -maxdepth 1 -type d -name 'uploads-*Z' \
            -newermt "-${MAX_BACKUP_AGE_HOURS} hours" -print -quit 2>/dev/null || true)"
        if [ -n "$snapshot" ]; then
            ok "a snapshot of the uploaded files newer than ${MAX_BACKUP_AGE_HOURS}h exists"
        else
            fail "no snapshot of the uploaded files ($UPLOADS) in $BACKUP_DIR newer than ${MAX_BACKUP_AGE_HOURS}h; journalctl -u gstbot-backup says why"
        fi
    fi
fi

# ---- Disk -----------------------------------------------------------------
# Outside the block above, not inside it. It used to sit in the branch where
# the backup directory exists and is readable, so a missing or unreadable
# directory — itself a problem worth reporting — also switched off the one
# check covering all four products on this box. The space is measured on the
# nearest directory that exists: when the backup directory is gone, the
# filesystem it would have been on is still the one tonight's dump fills.
disk_path="$BACKUP_DIR"
while [ ! -d "$disk_path" ] && [ "$disk_path" != / ]; do
    disk_path="$(dirname "$disk_path")"
done
free_mb="$(df -Pm "$disk_path" 2>/dev/null | awk 'NR == 2 { print $4 }' || true)"
if [ -z "$free_mb" ]; then
    fail "cannot read free space on $disk_path"
elif [ "$free_mb" -ge "$MIN_FREE_MB" ]; then
    ok "${free_mb}MiB free on $disk_path"
else
    fail "only ${free_mb}MiB free on $disk_path, below the ${MIN_FREE_MB}MiB floor"
fi

# ---- Serving --------------------------------------------------------------
# Two requests with different blast radii. The first failing and the second
# passing is impossible; the second failing alone is the edge, and knowing
# which without logging in is most of the value.
if curl -fsS --max-time 10 "$READY_URL" >/dev/null 2>&1; then
    ok "the API is ready on the bridge"
else
    fail "the API is not ready at $READY_URL"
fi

if curl -fsS --max-time 15 "$PUBLIC_URL" >/dev/null 2>&1; then
    ok "the site answers through the edge"
else
    fail "the site does not answer at $PUBLIC_URL (DNS, TLS or knol-caddy)"
fi

# ---- Report ---------------------------------------------------------------
# Read as well as fetched. A body that does not come back is already reported
# by the readiness check above, so only what the body says is added here.
HEALTH_HELPER="$(dirname "$(readlink -f "$0")")/monitor_health.py"
for kind in jobs health; do
    if [ "$kind" = jobs ]; then url="$JOBS_URL"; else url="$HEALTH_URL"; fi
    body="$(curl -sS --max-time 10 "$url" 2>/dev/null || true)"
    [ -n "$body" ] || continue
    found="$(printf '%s' "$body" | python3 "$HEALTH_HELPER" "$kind" "$MAX_QUEUE_DEPTH" || true)"
    if [ -z "$found" ]; then
        ok "$kind health reports nothing wrong"
    else
        while IFS= read -r line; do
            [ -n "$line" ] && fail "$line"
        done <<< "$found"
    fi
done

if [ "${#problems[@]}" -eq 0 ]; then
    echo "All checks passed"
    exit 0
fi

printf '%d check(s) failed\n' "${#problems[@]}" >&2

if [ -n "$WEBHOOK" ]; then
    # Built by python3 rather than by pasting strings into JSON: a problem
    # line carries a unit name, a path and a URL, and one quote in any of them
    # turns the alert into a 400 from the receiving end — a notification
    # channel that fails exactly when it is used is worse than none.
    payload="$(GSTBOT_PROBLEMS="$(printf '%s\n' "${problems[@]}")" \
               GSTBOT_HOST="$(hostname)" python3 - <<'PY'
import json
import os

problems = [line for line in os.environ["GSTBOT_PROBLEMS"].splitlines() if line]
host = os.environ["GSTBOT_HOST"]
summary = f"GSTBot on {host}: {len(problems)} check(s) failed"
# `text` is the field Slack, Discord and Mattermost incoming webhooks all
# read; the rest is there for anything that parses the body instead.
print(json.dumps({
    "text": summary + "\n" + "\n".join(f"- {p}" for p in problems),
    "service": "gstbot",
    "host": host,
    "problems": problems,
}))
PY
)"
    curl -fsS --max-time 15 -X POST -H 'Content-Type: application/json' \
        --data "$payload" "$WEBHOOK" >/dev/null \
        || echo "warning: the alert webhook did not accept the report" >&2
fi

# Non-zero, so `systemctl is-failed gstbot-monitor.service` is a single command
# that answers "is anything wrong" — including on the box where no webhook has
# been configured.
exit 1
