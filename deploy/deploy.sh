#!/usr/bin/env bash
# Release GSTBot on the Hetzner box. Run as root:
#
#   /opt/GSTBot/deploy/deploy.sh              # release origin/main
#   /opt/GSTBot/deploy/deploy.sh v1.2.0       # deploy a tag or sha, needs a remote
#
# First-time server setup is in deploy/README.md; this script assumes it has
# already been done and does nothing that is only correct once.
#
# **origin/main is the default source, and the tree is the fallback.** A
# read-only deploy key now lives on the box and is pinned in the checkout's
# core.sshCommand, so the no-argument release fetches and checks out
# origin/main. Before that key existed `git fetch` answered 401, an earlier
# version of this script fetched unconditionally and so could not release at
# all, and the fallback below — ship whatever rsync left in $ROOT — was the
# ordinary path. It is still the path on any box with no credential, which is
# why it stays; it is no longer the expected one here.
#
# The fallback is quiet enough to be dangerous, so it announces itself: a
# release that could not reach the remote says why, because a broken key and a
# box that never had one look identical from the outside and the first one
# ships stale code under a green release.
#
# Unlike a blue/green release, this builds in place: the checkout and the build
# output are the live ones. The box is shared with three other products and has
# roughly 2 GB of headroom, so keeping N releases of node_modules on disk and a
# second copy of the tree costs more than the seconds of downtime it removes.
# The frontend builds beside the live one, into dist.next, and is published by
# renaming it to dist — which is live the moment it happens, because
# static-server.mjs opens each file by path per request. So the rename waits
# for the migrations and goes just before the restart; see publish_frontend.
set -euo pipefail

ROOT=/opt/GSTBot
VENV="$ROOT/.venv"
LOCKFILE="$ROOT/backend/requirements.lock"
REF="${1:-}"
# The memory a frontend build on this box must find free before it starts, in
# MiB, and where to read it. See room_to_build.
BUILD_MIN_FREE_MB="${GSTBOT_BUILD_MIN_FREE_MB:-1536}"
MEMINFO="${GSTBOT_MEMINFO:-/proc/meminfo}"

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$*" >&2; }
die() { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

# Run from a copy, because the checkout further down replaces this file.
#
# Bash does not read a script into memory. It reads it lazily from the open
# descriptor, seeking back after each command so the offset stays honest — so
# a script that is rewritten while it runs does not carry on as it was and
# does not restart. The interpreter resumes at the byte offset it had reached,
# now pointing into different content, and runs whatever text happens to sit
# there: the tail of a command, half a `systemctl` line, or nothing at all if
# the new file is shorter and the offset is past its end.
#
# `git checkout` rewrites deploy/deploy.sh, and this is deploy/deploy.sh. The
# release that shipped retrying health checks ran the previous revision's
# single-shot ones off a file that had already been replaced on disk; a
# harness reproducing the same shape with a shorter successor exits silently,
# mid-release, reporting success.
#
# Copying first removes the problem rather than detecting it: git rewrites the
# path in $ROOT, this process is reading /tmp, and the two never meet. The
# consequence is that a release runs the script the operator invoked, whole,
# and a change to deploy.sh takes effect on the next one — announced below so
# that is a fact the operator is told rather than one they infer.
if [ -z "${GSTBOT_DEPLOY_PINNED:-}" ]; then
    pinned="$(mktemp "${TMPDIR:-/tmp}/gstbot-deploy.XXXXXX")" \
        || die "cannot create a temporary copy of this script"
    cat "$0" > "$pinned" || die "cannot copy $0"
    export GSTBOT_DEPLOY_PINNED="$pinned"
    exec bash "$pinned" "$@"
fi
trap 'rm -f "$GSTBOT_DEPLOY_PINNED"' EXIT

# One release at a time. Two concurrent runs both rebuild frontend/dist, and
# vite empties dist/ before it writes: on 2026-10-29 a second run's build
# failed after the first had finished, leaving index.html with no assets/ —
# a blank site for two minutes while /health still answered 200. Taken here,
# in the pinned copy that does the work, and held until it exits.
DEPLOY_LOCK="${GSTBOT_DEPLOY_LOCK:-/run/lock/gstbot-deploy.lock}"
exec 9>"$DEPLOY_LOCK" || die "cannot open the deploy lock $DEPLOY_LOCK"
flock -n 9 || die "another deploy is running (it holds $DEPLOY_LOCK); wait for it to finish"

# Is $ROOT a checkout this box can run git against at all? Separate from
# "can it reach the remote", which is the question below and has a different
# answer here.
have_checkout() { command -v git >/dev/null && [ -d "$ROOT/.git" ]; }

# Fetch origin, reporting why if it does not work. The fallback further down is
# legitimate on a box holding no credential, but from the outside that is
# indistinguishable from a box whose credential has broken — and the second one
# ships stale code while the release reports success. Whatever git said about
# it belongs on the operator's terminal, not in /dev/null.
fetch_origin() {
    local err
    if err="$(git -C "$ROOT" fetch --prune --tags origin 2>&1)"; then
        return 0
    fi
    warn "cannot fetch origin, so $ROOT will be released as it stands:"
    printf '%s\n' "$err" | sed 's/^/    /' >&2
    return 1
}

# A fetch that cannot authenticate must fail, not ask. Without these, git
# against a private HTTPS remote prompts for a username on the terminal and a
# release run from cron or a detached session hangs there indefinitely — which
# is the failure mode this script's fallback exists to avoid in the first place.
export GIT_TERMINAL_PROMPT=0

# BatchMode must not cost the deploy key. GIT_SSH_COMMAND *overrides*
# core.sshCommand rather than merging with it, and this checkout pins its
# read-only deploy key there (deploy/README.md) — so exporting a bare `ssh`
# here unauthenticates every fetch. The release then takes the "no reachable
# remote" path and ships whatever tree the box already had — and until
# fetch_origin above started reporting the reason, it did so in silence. The
# box sat twelve commits stale that way, across five green releases. Extend
# the pinned command rather than replacing it.
if [ -z "${GIT_SSH_COMMAND:-}" ]; then
    pinned_ssh=""
    if have_checkout; then
        pinned_ssh="$(git -C "$ROOT" config --get core.sshCommand || true)"
    fi
    export GIT_SSH_COMMAND="${pinned_ssh:-ssh} -o BatchMode=yes"
fi

[ "$(id -u)" -eq 0 ] || die "run as root (systemctl and $ROOT are root-owned)"
[ -d "$ROOT/backend" ] || die "$ROOT does not hold the application — see deploy/README.md"
[ -f /etc/gstbot/gstbot.env ] || die "/etc/gstbot/gstbot.env is missing"
[ -f "$LOCKFILE" ] || die "$LOCKFILE is missing; the tree in $ROOT predates it"
command -v npm >/dev/null || die "npm is not installed; the frontend is built here"

# The frontend is built on this box, so its Node is part of the release. CI
# tests one major (frontend/package.json engines.node) and the box ran another
# for months — CI on 20, the box on 22 — with nothing to say so. A release on a
# different major is refused before anything is built.
check_node() {
    local want have
    want="$(sed -nE 's/.*"node": *"[^0-9]*([0-9]+).*/\1/p' "$FRONTEND/package.json" | head -1)"
    have="$(node --version 2>/dev/null | sed -nE 's/^v([0-9]+).*/\1/p')"
    [ -n "$want" ] || die "frontend/package.json declares no engines.node to check this box against"
    [ "$have" = "$want" ] \
        || die "this box runs Node ${have:-none}, but the frontend is tested on Node $want (frontend/package.json engines.node); install Node $want before releasing"
}

log "Selecting the release source"
if [ -n "$REF" ]; then
    # An explicit ref is the one case where the remote is not optional: there
    # is nothing else that can turn "v1.2.0" into a tree. Failing here is the
    # honest answer, and it fails before anything has been changed.
    have_checkout || die "$ROOT is not a git checkout, so '$REF' cannot be resolved"
    git -C "$ROOT" fetch --prune --tags origin \
        || die "cannot fetch origin, so '$REF' cannot be resolved; see deploy/README.md"
    git -C "$ROOT" checkout --detach "$REF"
    echo "Checked out $REF"
elif have_checkout && fetch_origin; then
    git -C "$ROOT" checkout --detach origin/main
    echo "Checked out origin/main"
else
    # The fallback, not the expected path — see the header. Nothing is fetched
    # and nothing is checked out; the tree is released exactly as rsync left it.
    echo "No reachable remote — releasing the tree already in $ROOT"
fi

# Whether the checkout just changed the release procedure itself. This run is
# reading the copy taken at the top, so it is finishing under the script the
# operator invoked — correct, and not what someone who has just edited
# deploy.sh expects to see. Silence here is how that becomes "I fixed the
# deploy and it still did the old thing".
if ! cmp -s "$GSTBOT_DEPLOY_PINNED" "$ROOT/deploy/deploy.sh"; then
    warn "this release changed deploy.sh; the run finishing now is the previous"
    warn "version of it. Re-run the deploy to release under the new one."
fi

# What is about to be released, named as precisely as this box can name it.
# The rsync in the runbook copies .git along with everything else, so HEAD is
# the workstation's HEAD even when the remote is unreachable — which is why
# this stays a real revision rather than a timestamp.
if have_checkout; then
    REVISION="$(git -C "$ROOT" rev-parse --short HEAD)"
    # Tracked modifications only. Ignored paths (.venv, node_modules, dist)
    # live in this tree by design and would mark every release dirty.
    if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]; then
        REVISION="$REVISION-dirty"
        warn "the tree in $ROOT has uncommitted changes; releasing them"
    fi
else
    REVISION="unknown"
    warn "$ROOT is not a git checkout; the deployed revision cannot be named"
fi
echo "Deploying $REVISION"

log "Installing backend dependencies"
# The lock rather than requirements.txt. The latter is floors — `>=` — so
# installing from it resolves whatever PyPI published that morning, and a
# release differing from the one CI ran is exactly what a lock is for. It
# carries hashes, so pip refuses anything it did not resolve to.
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet --require-hashes -r "$LOCKFILE"
# And remove what the lock no longer names. pip never does: a package dropped
# from the lock stayed installed for good, out of sight of any audit of the
# lock. Production carried eight, python-jose and ecdsa among them, both with
# published vulnerabilities and neither imported by anything.
stale=$("$VENV/bin/python" "$ROOT/deploy/lock_extras.py" "$LOCKFILE") \
    || die "could not compare the virtualenv with $LOCKFILE"
if [ -n "$stale" ]; then
    echo "Removing packages the lock does not name: ${stale//$'\n'/ }"
    # shellcheck disable=SC2086 # one name per word, on purpose
    "$VENV/bin/pip" uninstall --quiet --yes $stale
fi

frontend_staged=""

# Put the staged build live. Not at the end of the build: renaming dist.next to
# dist is the frontend release, since gstbot-web reads files by path on every
# request — nothing waits for its restart. Done there, a backup or migration
# that then failed stopped the release with the new UI already live against the
# old API, and a release that went well served that mix for the length of the
# migration. Called once the migrations are in, just before the restart.
publish_frontend() {
    [ -n "$frontend_staged" ] || return 0
    rm -rf "$FRONTEND/dist.prev"
    if [ -d "$FRONTEND/dist" ]; then mv "$FRONTEND/dist" "$FRONTEND/dist.prev"; fi
    mv "$FRONTEND/dist.next" "$FRONTEND/dist"
    if [ -n "$source_id" ]; then echo "$source_id" > "$FRONTEND/.dist-source"; fi
}


log "Building the frontend"
# `npm ci` rather than `npm install`: the lockfile is the input, and a release
# that silently resolved a different version is not the thing that was tested.
#
# NODE_OPTIONS caps the heap. Node sizes its default from total RAM, which on a
# 4 GB box shared with three other products is well above what is actually
# free — the build then gets OOM-killed at the rollup stage instead of failing
# with something that names the cause.
#
# VITE_* settings are read from /etc/gstbot/gstbot.env, where every other
# setting lives. The build is the only thing that reads them — vite inlines
# them into the bundle — and the units' EnvironmentFile never reaches it, so a
# VITE_WHATSAPP_NUMBER put in gstbot.env (where the template said to look)
# silently did nothing. Read line by line rather than sourced: the file is
# systemd syntax, not shell.
#
# Built beside the live site, not in it. gstbot-web serves frontend/dist while
# this runs, and vite empties its outDir before writing: building in place
# took the site down for the length of every build (no index.html, no assets)
# and, when a build failed — out of memory, a compile error — left it down,
# because the release stops here and nothing after it restarts or restores
# anything. dist.next is swapped in only once it is complete; the build it
# replaces is kept as dist.prev, which is also what a quick rollback of the
# frontend puts back.
FRONTEND="$ROOT/frontend"
check_node
# What the build in dist was made from: the committed frontend tree and the
# VITE_* settings inlined into it. A release whose frontend is unchanged used
# to rebuild it anyway — npm ci from the registry and the slowest step here —
# to produce the same bytes. Unknown (no git, or uncommitted changes under
# frontend/) means always build.
frontend_source() {
    have_checkout || return 0
    [ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no -- frontend)" ] || return 0
    local tree vite
    tree="$(git -C "$ROOT" rev-parse HEAD:frontend 2>/dev/null)" || return 0
    vite="$({ grep -E '^VITE_[A-Z0-9_]*=' /etc/gstbot/gstbot.env 2>/dev/null || true; } \
        | sha256sum | cut -c1-16)"
    echo "$tree-$vite"
}
# A build made somewhere else, uploaded to frontend/dist.upload with the source
# id it was built from in dist.upload/.source. The box has 8 GB shared by many
# products, and on 2026-10-29 a build here swapped it to a load average of 180,
# SSH stopped answering for the length of it, and the build was killed with
# the release half-done; the way round that was a wrapper that pre-seeded
# .dist-source to fool this script out of its own build. An upload is checked
# against the tree being released — one built from anything else is discarded,
# never published — and then staged exactly as a build made here would be.
#
#   1. build frontend/ from the commit being released, on a machine with
#      the memory (the lockfile install, then the build script);
#   2. write "$(git rev-parse HEAD:frontend)-<vite hash>" to dist/.source;
#   3. rsync -a --delete dist/ server:/opt/GSTBot/frontend/dist.upload/
#
# The vite hash is the second half of frontend_source's id: the first 16 hex
# digits of sha256 over the VITE_* lines in /etc/gstbot/gstbot.env.
stage_uploaded_build() {
    local upload="$FRONTEND/dist.upload" made
    [ -f "$upload/index.html" ] || return 1
    made="$(cat "$upload/.source" 2>/dev/null || true)"
    if [ -z "$source_id" ] || [ "$made" != "$source_id" ]; then
        warn "dist.upload was built from ${made:-an unrecorded tree}, not ${source_id:-a known one}; discarding it"
        rm -rf "$upload"
        return 1
    fi
    rm -f "$upload/.source"
    rm -rf "$FRONTEND/dist.next"
    mv "$upload" "$FRONTEND/dist.next"
}

# Whether this box has the memory for a build right now. A build that starts
# without it does not fail fast: it swaps every product here into the ground
# first, and is killed at the end anyway. Unknown (no MemAvailable) does not
# block — the floor is protection, not a dependency.
room_to_build() {
    local available_kb
    available_kb="$(awk '/^MemAvailable:/ { print $2 }' "$MEMINFO" 2>/dev/null || true)"
    [ -n "$available_kb" ] || return 0
    [ $((available_kb / 1024)) -ge "$BUILD_MIN_FREE_MB" ]
}

source_id="$(frontend_source)"
if [ -n "$source_id" ] && [ -f "$FRONTEND/dist/index.html" ] \
    && [ "$(cat "$FRONTEND/.dist-source" 2>/dev/null)" = "$source_id" ]; then
    echo "The frontend is unchanged since the build it is serving; not rebuilding it"
    rm -rf "$FRONTEND/dist.upload"
elif stage_uploaded_build; then
    frontend_staged=1
    echo "Staged the uploaded build into dist.next; it goes live after the migrations"
else
    rm -f "$FRONTEND/.dist-source"
    rm -rf "$FRONTEND/dist.next"
    room_to_build || die "under ${BUILD_MIN_FREE_MB}MiB of memory free, so the frontend is not built here; build it elsewhere and upload it to frontend/dist.upload (see stage_uploaded_build), or set GSTBOT_BUILD_MIN_FREE_MB"
    ( cd "$FRONTEND" \
        && while IFS= read -r line; do
               # shellcheck disable=SC2163 # each line is NAME=value, exported as one
               case "$line" in VITE_[A-Z0-9_]*=*) export "$line" ;; esac
           done < /etc/gstbot/gstbot.env \
        && npm ci --no-audit --no-fund \
        && GSTBOT_BUILD_DIR=dist.next NODE_OPTIONS=--max-old-space-size=768 npm run build ) \
        || die "the frontend did not build; the site still serves the previous build"
    [ -f "$FRONTEND/dist.next/index.html" ] \
        || die "build produced no index.html; the site still serves the previous build"
    frontend_staged=1
    echo "Built into dist.next; it goes live after the migrations"
fi

log "Installing changed systemd units"
# The units were installed once, by hand, from deploy/README.md, and no release
# touched them again — so a unit edit committed here (a timeout, a restart
# policy, a new ExecStart flag) reached main, passed CI, and never reached the
# box. On 2026-10-29 every installed service still named the product's old
# domain. Only files that differ are written, so an unchanged release leaves
# /etc/systemd/system alone, and timers are restarted so a new schedule is the
# one that fires. Before the restore point, so a changed backup unit is the one
# that takes it.
changed_units=()
for unit in "$ROOT"/deploy/systemd/*; do
    name=$(basename "$unit")
    if ! cmp -s "$unit" "/etc/systemd/system/$name"; then
        install -m 0644 "$unit" "/etc/systemd/system/$name"
        changed_units+=("$name")
    fi
done
if [ "${#changed_units[@]}" -gt 0 ]; then
    systemctl daemon-reload
    echo "updated: ${changed_units[*]}"
    for name in "${changed_units[@]}"; do
        case "$name" in
            *.timer) systemctl is-enabled --quiet "$name" && systemctl restart "$name" ;;
        esac
    done
else
    echo "unchanged"
fi

log "Taking a restore point"
# The migration below is the one step of a release that is not undone by
# deploying the previous revision: code goes back, a dropped column does not.
# So the dump happens here, immediately before it, rather than being left to
# tonight's timer — a restore point taken twelve hours before the change it
# exists to undo is not a restore point.
#
# `systemctl start`, not a call to backup.sh: the unit carries the service
# account, the sandbox and the EnvironmentFile, so this is the same dump the
# timer takes rather than a second code path that could work when that one
# does not. Type=oneshot, so this blocks until the dump has been written and
# read back, and reports its exit status.
#
# After the build on purpose. A frontend that does not compile should cost
# nothing, and the dump is only worth taking once the release is otherwise
# going to happen.
if [ -n "${GSTBOT_SKIP_BACKUP:-}" ]; then
    # The escape hatch exists for one situation: the disk is full and this
    # release is the fix. It is loud because every other use of it is a
    # migration applied with no way back.
    warn "GSTBOT_SKIP_BACKUP is set — migrating with no restore point"
else
    systemctl start gstbot-backup.service \
        || die "backup failed, so nothing is migrated; journalctl -u gstbot-backup -n 50"
fi

log "Applying migrations"
# Ahead of the restart, and on its own, so a migration that fails stops the
# release rather than leaving a half-started stack behind it. `restart` rather
# than `start`: the unit is RemainAfterExit=yes, so it is already "active" from
# the last release and `start` would be a no-op.
systemctl restart gstbot-migrate.service \
    || die "migrations failed; journalctl -u gstbot-migrate -n 100"

log "Restarting services"
# reset-failed first: it also clears each unit's start counter. The units allow
# five starts in 300 s (StartLimitBurst) so that a crash loop stops instead of
# spinning — and a release's restart counted against that like a crash did. On
# 2026-10-29 the third release inside five minutes was refused with
# start-limit-hit, and the API and worker stayed down for four minutes. A
# deliberate restart is not the loop the limit is for. And it says so if it
# fails: under `set -e` alone the release stopped here with no error line, which
# read like a deploy still running.
SERVICES=(gstbot-api.service gstbot-web.service gstbot-worker.service gstbot-beat.service)
# The revision the restarted API reports as `release` on /health. Read once per
# process, so it names the code that process loaded: an API that failed to
# restart keeps answering 200 with the previous one, and that is now visible.
printf '%s\n' "$REVISION" > "$ROOT/backend/.release"
publish_frontend
systemctl reset-failed "${SERVICES[@]}" 2>/dev/null || true
systemctl restart "${SERVICES[@]}" \
    || die "the services did not restart; systemctl status ${SERVICES[*]} — then journalctl -u gstbot-api -n 100"

log "Checking health"

# Poll a URL until it answers, and say how long that took. Every check here is
# made immediately after a restart, so every one of them is asking a question
# whose answer is "not yet" for a while — the difference between them is only
# how long that while is.
await() {
    local what="$1" url="$2" seconds="$3" hint="$4" attempt
    for attempt in $(seq 1 "$seconds"); do
        if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
            echo "$what after ${attempt}s"
            return 0
        fi
        sleep 1
    done
    die "$what did not happen within ${seconds}s; $hint"
}

await "API is ready" http://172.18.0.1:3008/api/v1/health/ready 30 \
    "journalctl -u gstbot-api -n 100"
await "the SPA is being served" http://172.18.0.1:3009/ 30 \
    "journalctl -u gstbot-web -n 100"

# 45s, not one shot. This is the only check that goes through the edge, and
# the edge does not learn the API is back at the same time the API does.
# Caddy runs an *active* health check against the upstream on a 30s interval
# (see deploy/caddy-gstbot.conf), so a probe that happens to land during the
# uvicorn restart marks the upstream down and holds that verdict until the
# next one — up to 30 seconds after the API is answering perfectly well on the
# bridge. The check above proves that and returns in about 4 seconds.
#
# So a single-shot curl here was a coin toss on where in Caddy's cycle the
# restart fell, and losing it failed a release that had already succeeded:
# services up, migrations applied, new code serving, and an error telling the
# operator to go read the edge logs. Waiting past one full interval is what
# makes this check report the edge's steady state rather than its blind spot.
await "the site is answering through Caddy" \
    https://gst.doaide.com/api/v1/health/live 45 \
    "docker logs knol-caddy --tail 100"

# The timers the one-time setup enables (deploy/README.md). No release step
# depends on them, so a skipped `enable --now` is invisible: on 2026-10-29
# gstbot-monitor.timer had sat installed and disabled since August, and
# nothing was watching the backups, the disk or a unit that had given up.
# A warning rather than a failure — the release itself has succeeded — said on
# every deploy until it is put right.
for timer in gstbot-backup.timer gstbot-monitor.timer; do
    systemctl is-enabled --quiet "$timer" 2>/dev/null \
        || warn "$timer is not enabled, so it never runs: systemctl enable --now $timer"
done

log "Deployed $REVISION"
systemctl --no-pager --lines=0 status gstbot.target || true
