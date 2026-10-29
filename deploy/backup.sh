#!/usr/bin/env bash
# Dump the GSTBot database, prove the dump is readable, and prune what has
# aged out. Run by gstbot-backup.timer; safe to run by hand:
#
#   systemctl start gstbot-backup.service        # exactly what the timer does
#   sudo -u gstbot /opt/GSTBot/deploy/backup.sh  # same, without the sandbox
#
# The database holds tax documents with a statutory retention period, so the
# thing this guards against is not only disk failure — it is a bad migration
# or a mistaken delete, which a snapshot of the volume taken afterwards would
# happily preserve.
#
# Two limits worth knowing rather than discovering:
#
#   * The dumps land on the same disk as the database. That covers operator
#     error and corruption; it does not cover losing the box. Copying $DEST
#     off-host is a separate job and is not done yet.
#   * /var/lib/gstbot/invoices holds the uploaded originals and is not dumped
#     here. A restore gives back every row, including the paths of files that
#     are no longer there.
#
# Postgres is shared with the other products on this box. This dumps one
# database, by name, as the one role that owns it — never `pg_dumpall`, which
# would put Herald's and HomeNex's data in a file owned by GSTBot's service
# account.
set -euo pipefail

# Every knob is an environment variable with a default, so the unit file can
# stay declarative and a one-off restore drill can point the script at a
# scratch directory without editing it.
ENV_FILE="${GSTBOT_ENV_FILE:-/etc/gstbot/gstbot.env}"
DEST="${GSTBOT_BACKUP_DIR:-/var/backups/gstbot}"
RETENTION_DAYS="${GSTBOT_BACKUP_RETENTION_DAYS:-14}"
# A dump that fills the disk takes out four products, not one. This is the
# floor the dump refuses to start below, in MiB.
MIN_FREE_MB="${GSTBOT_BACKUP_MIN_FREE_MB:-1024}"

log() { printf '%s\n' "$*"; }
die() { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

# ---- Connection details ---------------------------------------------------
# Under systemd the unit's EnvironmentFile has already put DATABASE_URL in the
# environment. By hand it has not, so fall back to reading the one line out of
# the env file rather than sourcing it — that file is systemd's format, not
# shell, and sourcing it would execute anything a future value contained.
if [ -z "${DATABASE_URL:-}" ]; then
    [ -r "$ENV_FILE" ] || die "$ENV_FILE is not readable and DATABASE_URL is unset"
    DATABASE_URL="$(sed -n 's/^DATABASE_URL=//p' "$ENV_FILE" | tail -n 1)"
    [ -n "$DATABASE_URL" ] || die "no DATABASE_URL in $ENV_FILE"
fi

command -v pg_dump >/dev/null || die "pg_dump is missing (apt install postgresql-client)"
command -v pg_restore >/dev/null || die "pg_restore is missing (apt install postgresql-client)"
command -v python3 >/dev/null || die "python3 is missing; it parses DATABASE_URL below"

# Split the URL with a real URL parser rather than a regex: the password is
# percent-encoded in there, and a `@` or `%` in it is the kind of thing that
# silently produces a wrong host at 02:30 and an empty backup directory by the
# time anyone looks. The SQLAlchemy driver suffix (`+psycopg`) is ignored.
#
# The result is exported as libpq's PG* variables instead of being passed to
# pg_dump as a URI, so the password never appears in the argv of a process on
# a box four products can read `ps` on.
connection="$(DATABASE_URL="$DATABASE_URL" python3 - <<'PY'
import os
import shlex
import sys
from urllib.parse import unquote, urlsplit

url = urlsplit(os.environ["DATABASE_URL"])
# Decoded: a URL carries a password with "@", "/" or "%" in it percent-encoded,
# and urlsplit hands the parts back still encoded, so PGPASSWORD was "p%40ss"
# for "p@ss" and every dump failed to authenticate.
database = unquote(url.path.lstrip("/"))
if not url.hostname or not database:
    sys.exit("DATABASE_URL names no host or no database")

for name, value in (
    ("PGHOST", url.hostname),
    ("PGPORT", str(url.port or 5432)),
    ("PGUSER", unquote(url.username or "")),
    ("PGPASSWORD", unquote(url.password or "")),
    ("PGDATABASE", database),
):
    print(f"export {name}={shlex.quote(value)}")
PY
)" || die "DATABASE_URL in $ENV_FILE is not a URL this can dump"
eval "$connection"

# ---- Preflight ------------------------------------------------------------
[ -d "$DEST" ] || die "$DEST does not exist; see 'Backups' in deploy/README.md"
[ -w "$DEST" ] || die "$DEST is not writable by $(id -un)"

free_mb="$(df -Pm "$DEST" | awk 'NR == 2 { print $4 }')"
[ "${free_mb:-0}" -ge "$MIN_FREE_MB" ] \
    || die "only ${free_mb}MiB free on $DEST, below the ${MIN_FREE_MB}MiB floor"

# ---- Dump -----------------------------------------------------------------
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$DEST/${PGDATABASE}-${stamp}.dump"
partial="$target.partial"
# Written under a .partial name and renamed only once pg_restore has read it
# back, so the retention sweep below can treat every *.dump as restorable and
# an interrupted run leaves nothing that looks like a backup.
trap 'rm -f "$partial"' EXIT

umask 077
log "Dumping $PGDATABASE from $PGHOST:$PGPORT"
# --format=custom, not plain SQL: it compresses, and it is the only format
# pg_restore can read selectively — restoring one table out of it during an
# incident does not mean replaying the whole database.
pg_dump --format=custom --compress=9 --no-owner --no-privileges --file="$partial" \
    || die "pg_dump failed; the previous dumps in $DEST are untouched"

# A dump that exits 0 can still be truncated by a full disk. Reading the table
# of contents back is cheap and is the difference between having backups and
# believing you do.
pg_restore --list "$partial" >/dev/null \
    || die "pg_dump wrote $partial but pg_restore cannot read it"

mv "$partial" "$target"
log "Wrote $target ($(du -h "$target" | cut -f1))"

# ---- Retention ------------------------------------------------------------
# Only reached after a dump that verified, so this cannot leave the directory
# empty — unless RETENTION_DAYS is 0, which would delete the file just written
# and is treated as a configuration error rather than a policy.
[ "$RETENTION_DAYS" -ge 1 ] || die "GSTBOT_BACKUP_RETENTION_DAYS must be at least 1"
find "$DEST" -maxdepth 1 -type f -name '*.dump' -mtime "+$RETENTION_DAYS" -print -delete \
    | sed 's/^/Pruned /'

# Every release takes a restore point as well as the nightly run, so age alone
# let the count follow how often anyone deployed — 162 dumps after one busy
# day, mostly identical. Past a day old only one a day is worth keeping: the
# newest of that day. Within the last day every one stays, since the latest
# release's restore point is the one a rollback reaches for. Thinning rather
# than a count cap, which a burst of releases would turn into deleting the
# nightly dumps a problem noticed late needs. Names carry a UTC stamp, so they
# sort in time order without anything GNU-only.
thin_dumps() {
    local path name day previous=""
    find "$DEST" -maxdepth 1 -type f -name '*.dump' -mtime +0 | sort -r |
    while IFS= read -r path; do
        name="${path##*/}"
        day="$(printf '%s\n' "$name" | sed -nE 's/.*-([0-9]{8})T[0-9]{6}Z\.dump$/\1/p')"
        [ -n "$day" ] || continue
        if [ "$day" = "$previous" ]; then
            rm -f -- "$path"
            echo "Thinned $name"
        fi
        previous="$day"
    done
}
thin_dumps

kept="$(find "$DEST" -maxdepth 1 -type f -name '*.dump' | wc -l)"
log "$kept dump(s) in $DEST, keeping ${RETENTION_DAYS} days"
