#!/usr/bin/env bash
# Put the previous frontend build back, without touching the API.
#
#   /opt/GSTBot/deploy/rollback-frontend.sh
#
# deploy.sh keeps the build each release replaces as frontend/dist.prev. This
# swaps the two, so running it again undoes it. gstbot-web serves whatever
# dist holds, file by file, so no restart is needed.
#
# It replaces a two-command recipe in the README that did harm when there was
# nothing to go back to: `mv dist dist.bad && mv dist.prev dist` moved the live
# build away first, then failed — and left the site with no dist at all. On a
# fresh box, or after a rollback had already used dist.prev, the rollback was
# the outage. Every check here happens before anything moves.
set -euo pipefail

FRONTEND="${GSTBOT_FRONTEND_DIR:-/opt/GSTBot/frontend}"
LOCK="${GSTBOT_DEPLOY_LOCK:-/run/lock/gstbot-deploy.lock}"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# A release swaps these same directories; the two must not interleave.
exec 9>"$LOCK" || die "cannot open the deploy lock $LOCK"
flock -n 9 || die "a deploy is running (it holds $LOCK); wait for it to finish"

[ -f "$FRONTEND/dist.prev/index.html" ] \
    || die "there is no previous build to go back to ($FRONTEND/dist.prev has no index.html); the site is unchanged. Redeploy the previous revision instead: deploy.sh <sha>"
[ -f "$FRONTEND/dist/index.html" ] \
    || die "$FRONTEND/dist has no index.html, so this is not the layout a release leaves; the site is unchanged"

rm -rf "$FRONTEND/dist.swap"
mv "$FRONTEND/dist" "$FRONTEND/dist.swap"
mv "$FRONTEND/dist.prev" "$FRONTEND/dist"
mv "$FRONTEND/dist.swap" "$FRONTEND/dist.prev"
# What deploy.sh recorded about the build in dist is no longer true of it, so
# the next release must not skip its build on the strength of it.
rm -f "$FRONTEND/.dist-source"
echo "Rolled the frontend back; the build it replaced is now dist.prev (run again to undo)."
