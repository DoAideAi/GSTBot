# Deploying GSTIndia

Target: the shared Hetzner box (Ubuntu 24.04, aarch64, 4 GB) that also runs
GoSumo, Documedic, Herald and the knol stack, serving `gst.doaide.com`.
Postgres, Redis, the API, the web server, the Celery worker and the scheduler
are host processes; the edge is a container.

```
                    ┌──────────────────────────────────────────────┐
  :443 ── knol-caddy┤ /api/*  → 172.18.0.1:3008  (uvicorn)         │
       (container)  │ /*      → 172.18.0.1:3009  (static-server)   │
                    └──────────────────────────────────────────────┘
                                     │  docker bridge knol_knol
                     gstbot-api ─────┼───── gstbot-worker ── gstbot-beat
                                     │
              Postgres :5432 (shared) │ Redis :6379 db 6,7,8 (shared)
```

Two things about this box drive most of what follows.

**Caddy runs in a container.** `knol-caddy` serves every site on the host from
one file, `/opt/knol/Caddyfile`, bind-mounted read-only. It cannot read
`/opt/GSTBot/frontend/dist`, so the SPA needs a process to serve it — hence
`gstbot-web`, which a host Caddy would not need. Both upstreams bind
`172.18.0.1`, the bridge gateway: reachable from the edge container, not routed
from the internet. Binding loopback would hide them from Caddy; binding
`0.0.0.0` would publish the API unencrypted on the public address next to the
TLS one.

**Postgres and Redis are shared.** Redis has no isolation between numbered
databases, and db0 (GoSumo's BullMQ), db1 (Herald's Celery broker) and db3/4/5
(CAFlow) are taken, so GSTIndia uses db6/7/8. Port 8000 is taken as well, by
`authmatic-agent` — GSTIndia's API is on 3008 and the SPA on 3009, following the
300x convention the other products on the box use.

## Layout on the server

| Path | What it is | Owner |
|---|---|---|
| `/opt/GSTBot` | git checkout, detached at the deployed revision | `root` |
| `/opt/GSTBot/.venv` | backend virtualenv | `root` |
| `/opt/GSTBot/frontend/dist` | built SPA, served by `gstbot-web` | `root` |
| `/var/lib/gstbot/invoices` | uploaded invoices | `gstbot` |
| `/var/backups/gstbot` | nightly `pg_dump` output, `0700` | `gstbot` |
| `/etc/gstbot/gstbot.env` | configuration and secrets, `0640 root:gstbot` | `root` |

The application user owns exactly one of these. It uploads invoices; it does
not need to be able to rewrite its own code, and under `ProtectSystem=strict`
it cannot.

## First-time setup

Run as root. Each step is safe to repeat.

**1. Packages**

Python, Node, Postgres, Redis and Docker are already on this box for the other
products. The one thing GSTIndia adds:

```sh
apt update && apt install -y tesseract-ocr python3.12-venv
```

`tesseract-ocr` is the OCR fallback for photographed invoices when no vision
model is reachable — without it those uploads fail rather than degrade.

`python3.12` is named rather than `python3` because it is the interpreter CI
runs the suite on, and it is the only one this application is known to work on.
Debian's `python3` is whatever the release defaults to; on a box that has been
upgraded once that is no longer the same thing. `python3.12-venv` is a separate
package on Debian — `python3 -m venv` fails with a message about `ensurepip`
without it, which reads like a broken interpreter rather than a missing package.

**2. Service account and directories**

```sh
useradd --system --home-dir /var/lib/gstbot --shell /usr/sbin/nologin gstbot
install -d -m 0750 -o root -g gstbot /etc/gstbot
install -d -m 0700 -o gstbot -g gstbot /var/backups/gstbot
```

`/var/lib/gstbot` is not created here: `StateDirectory=gstbot` in the units
creates it with the right owner and mode the first time a unit starts, and a
hand-made one with the wrong owner is a confusing way to discover that.

`/var/backups/gstbot` is the exception, because systemd has no equivalent for
it: `gstbot-backup.service` names it in `ReadWritePaths=`, which fails to
start if the directory does not exist rather than creating it. `0700`, because
a dump is every invoice, every GSTIN and the user table in one file on a box
four products can read.

**3. Database**

```sh
sudo -u postgres createuser gstbot --pwprompt
sudo -u postgres createdb gstbot --owner gstbot
```

**4. Code and virtualenv**

The repository is private and this box has no credential for it, so the tree is
pushed from a workstation rather than cloned. `--delete` keeps the server from
accumulating files that a later revision removed; `node_modules` and the builds
(`dist`, and the `dist.next` and `dist.prev` a release leaves beside it) are
excluded because they are built on the server, from the lockfile, in step 8.

```sh
# from a workstation, in the repository root
rsync -az --delete --no-owner --no-group \
    --exclude .venv --exclude node_modules --exclude dist --exclude 'dist.*' \
    --exclude __pycache__ --exclude .pytest_cache \
    -e "ssh -i path/to/hetzner_deploy_ed25519" \
    ./ root@89.167.8.178:/opt/GSTBot/

# on the server
python3.12 -m venv /opt/GSTBot/.venv
/opt/GSTBot/.venv/bin/pip install --require-hashes -r /opt/GSTBot/backend/requirements.lock
```

`requirements.lock`, not `requirements.txt`. The latter is floors (`>=`), so
installing from it resolves whatever PyPI published that morning; the lock is
the exact set, with hashes, and is the only thing a release installs. It is
compiled from the floors on a workstation — see "Dependencies" below.

`--no-owner --no-group` matters. Without them rsync running as root recreates
the *sender's* numeric ids, and a macOS workstation's `501:staff` is not a user
on this box — the tree lands owned by a uid that does not exist, which is
neither root nor `gstbot` and confusing to read later.

Because of this, `deploy.sh` cannot fetch on its own — see "Releasing".

**5. Configuration**

```sh
install -m 0640 -o root -g gstbot \
    /opt/GSTBot/deploy/gstbot.env.example /etc/gstbot/gstbot.env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # JWT_SECRET
$EDITOR /etc/gstbot/gstbot.env                                  # the REPLACE_ME values
```

The shipped template will not boot: its `JWT_SECRET` is too short for the
production length check. That is deliberate — a template that started is a
template somebody would have left alone.

**6. Units**

```sh
install -m 0644 /opt/GSTBot/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gstbot.target
systemctl enable --now gstbot-backup.timer
systemctl enable --now gstbot-monitor.timer
```

The install is needed once; enabling is the part only you can do. After this,
every `deploy.sh` copies any unit file that changed in the repo into
`/etc/systemd/system`, reloads systemd and restarts a changed timer, so a unit
edit ships like any other change. It never enables or disables anything.

That installs ten units:

| Unit | What it is |
|---|---|
| `gstbot.target` | the handle for the stack — start, stop and restart all of it |
| `gstbot-migrate.service` | `alembic upgrade head`, once, before anything queries the schema |
| `gstbot-api.service` | uvicorn on `172.18.0.1:3008` |
| `gstbot-web.service` | the built SPA on `172.18.0.1:3009` |
| `gstbot-worker.service` | the Celery worker that extracts invoices |
| `gstbot-beat.service` | the scheduler — see "The daily sweep" |
| `gstbot-backup.service` | one `pg_dump`, started by the timer — see "Backups" |
| `gstbot-backup.timer` | 02:30 nightly |
| `gstbot-monitor.service` | one pass of the health checks — see "Monitoring" |
| `gstbot-monitor.timer` | every 15 minutes |

`gstbot-migrate.service` is a `oneshot` that stays active after it exits, and
both serving units `Requires=` it. That is what stops two processes running
`alembic upgrade` against one database at the same time — the same rule the
container entrypoint follows when it refuses to migrate from the worker.

Both timers are enabled separately and on purpose. Neither is in
`gstbot.target`, so `systemctl restart gstbot.target` during a release does
not fire a dump or run a health check against units that are mid-restart — and
the price of that is two units `enable --now gstbot.target` does not reach.
Enabling the target and forgetting the timers is the way this box ends up with
no backups and no sign of it, so both lines are part of step 6 rather than a
footnote. `gstbot-monitor` reports the other one being missed; nothing reports
`gstbot-monitor` being missed, so it is the one to check twice.

**7. Edge**

Append `deploy/caddy-gstbot.conf` to `/opt/knol/Caddyfile`, then:

```sh
docker exec knol-caddy caddy validate --config /etc/caddy/Caddyfile
docker exec knol-caddy caddy reload  --config /etc/caddy/Caddyfile
```

`reload`, not a container restart: the other sites on that instance are
serving, and a restart drops their connections to publish ours.
`gst.doaide.com` must already resolve to this box, or the certificate order
fails and Caddy retries with a backoff.

**8. First release**

```sh
/opt/GSTBot/deploy/deploy.sh
```

## Releasing

A release is one command, run on the server:

```sh
/opt/GSTBot/deploy/deploy.sh              # origin/main
/opt/GSTBot/deploy/deploy.sh v1.2.0       # a tag or a sha
```

Push to `main` first — that is what the no-argument form releases. A read-only
deploy key for `r2st/GSTBot` lives on the box and is pinned in the checkout's
`core.sshCommand`, so `deploy.sh` fetches and checks out `origin/main` itself.
Nothing has to be copied from a workstation.

The script installs the locked dependencies, builds the frontend, takes a
database dump, migrates, restarts the services and then checks readiness on the
bridge and `/health/live` through Caddy. Anything that fails stops the release.

The frontend is built into `frontend/dist.next`, beside the `dist` the site is
serving, and swapped in only once it has produced an `index.html`; the build it
replaces is kept as `frontend/dist.prev`. A build that fails therefore stops the
release with the previous site still up, rather than an emptied `dist`.

The restart clears each unit's failed state first, which also resets its start
counter. The units allow five starts in five minutes so that a crash loop stops;
a release's restart used to count against that, and the third release inside
five minutes was refused with `start-limit-hit`, leaving the API down until it
was started by hand.

The dump is the nightly backup unit, started synchronously — see "Backups". It
runs because the migration is the one step of a release that redeploying the
previous revision does not undo: the code goes back, a dropped column does not.
A dump that fails stops the release before anything is migrated, on the
grounds that the next step is the unrecoverable one. When that is the wrong
call — the disk is full and this release is the fix — the way past it is

```sh
GSTBOT_SKIP_BACKUP=1 /opt/GSTBot/deploy/deploy.sh
```

which migrates with no restore point and says so.

One release runs at a time. The script holds `flock` on
`/run/lock/gstbot-deploy.lock` (override with `GSTBOT_DEPLOY_LOCK`) for its
whole run, and a second start exits at once with "another deploy is running".
Two concurrent builds once left `frontend/dist` with no `assets/` — a blank
site while `/health` still said 200. To see whether one is running:

```sh
flock -n /run/lock/gstbot-deploy.lock true && echo free || echo busy
```

The script re-executes from a copy in `/tmp/gstbot-deploy.*`, so look for that
rather than `deploy/deploy.sh` in `ps`. `VITE_*` lines in
`/etc/gstbot/gstbot.env` are exported into the frontend build, so changing one
needs a deploy, not a restart.

**Watch the source line, because the fallback is quiet.** If the fetch fails,
`deploy.sh` does not stop — it releases the tree already in `/opt/GSTBot`, which
is the supported path on a box holding no credential and the wrong one here:

```
==> Selecting the release source
warning: cannot fetch origin, so /opt/GSTBot will be released as it stands:
warning:   git@github.com: Permission denied (publickey).
No reachable remote — releasing the tree already in /opt/GSTBot
Deploying ff2412c
```

That is a stale release reporting success, and it has happened: `43c4976` fixed
a `GIT_SSH_COMMAND` export that replaced the pinned `core.sshCommand` instead of
extending it, throwing the deploy key away on every fetch. The box sat twelve
commits behind across five green releases. The two warning lines are there
because a box whose key broke and a box that never had one look identical from
the outside, and only the first ships code nobody chose.

So the check after a release is `Deploying <sha>` against what you pushed. A
`-dirty` suffix means the checkout has uncommitted changes and they are going
out too. If the fetch is what broke, `git -C /opt/GSTBot fetch origin` by hand
says why, and `git -C /opt/GSTBot config --get core.sshCommand` should name the
deploy key.

Pushing the tree by hand — the step-4 `rsync` — is still how a box with no
remote is released, and still how this one is bootstrapped before the key is in
place. An explicit ref is the one thing it cannot substitute for: `deploy.sh
v1.2.0` needs a remote and refuses with a message rather than releasing the
wrong tree. The rollback below assumes one too.

It builds in place rather than blue/green. On a 4 GB box shared with three
other products, keeping N releases of `node_modules` and a second copy of the
tree costs more than the seconds of downtime it removes.

## Dependencies

`backend/requirements.txt` holds floors (`>=`); `backend/requirements.lock` is
the same set resolved to exact versions, with hashes. The server installs the
lock, and so does CI, before adding the test tools on top — so a release cannot
quietly differ from the one the suite ran against. (CI used to install the
floors alone, which resolved whatever PyPI had that day: the suite ran on
SQLAlchemy 2.1 while production ran 2.0.) A Dependabot bump to a floor still
verifies itself: `test_requirements.py` fails until the lock is recompiled.

Recompile the lock on a workstation whenever `requirements.txt` changes, and
commit both in the same change:

```sh
uv pip compile backend/requirements.txt --universal --python-version 3.12 \
    --generate-hashes -o backend/requirements.lock
```

`--python-version 3.12` is the interpreter on the server, not the one on the
workstation; `--universal` keeps the markers that let the same file resolve on
both. `backend/tests/test_requirements.py` fails if a floor is raised without
the lock being recompiled, or if the lock stops being a complete hash-checked
closure — the two ways this arrangement rots.

The lock is also everything the server has. `pip install -r` adds and upgrades
but never removes, so a release then runs `deploy/lock_extras.py` and uninstalls
whatever the virtualenv holds that the lock does not name (pip, setuptools and
the project's own install aside). Before that, packages dropped from the lock
stayed installed for good, two with published vulnerabilities, out of sight of
any audit of the lock. To see what it would remove:

```sh
/opt/GSTBot/.venv/bin/python /opt/GSTBot/deploy/lock_extras.py /opt/GSTBot/backend/requirements.lock
```

## Operating

```sh
systemctl status gstbot.target                # everything
journalctl -u gstbot-api -f                   # API logs (JSON)
journalctl -u gstbot-worker -f                # extraction logs
systemctl restart gstbot.target               # migrate, then API, web and worker

curl -s 172.18.0.1:3008/api/v1/health | jq    # every dependency, with latency
```

`/api/v1/health` answers 200 while degraded and names what is degraded. A
missing `OPENROUTER_API_KEY` or a dead Redis is not an outage — extraction
falls back to heuristics and parsing runs inline — so page on `/health/ready`,
which is 503 only when the database is unreachable.

Its `checks.integrations` block says which optional features this server can
offer, from configuration alone (nothing is called): `advisor` (the GST advisor
chat, needs `GEMINI_API_KEY` or `GEMINI_API_KEY_FILE`), `payments`
(`RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`; `webhooks` is whether
`RAZORPAY_WEBHOOK_SECRET` is set) and `email` (deadline alert emails:
`ALERTS_EMAIL_ENABLED` and `SMTP_HOST`). `unconfigured` or `disabled` there is
a feature switched off, not a fault, and does not change `status`;
`misconfigured` (email switched on with no `SMTP_HOST`) is a mistake to fix.

Every log line and every response carries a correlation id (`X-Request-ID`).
It is what turns a user's screenshot into a journal query:

```sh
journalctl -u gstbot-api -u gstbot-worker --since today \
    | grep 9f2c1a0b4e7d5a63
```

The id survives the broker, so the upload and the parse it triggered are one
trace across both units.

### Rollback

```sh
/opt/GSTBot/deploy/deploy.sh <previous-sha>
```

A migration is not rolled back by that. `alembic downgrade` is exercised in CI
in both directions, so it works — but it is a decision to take with the data in
front of you, not something a deploy script should do while an incident is in
progress.

Nor does it fail on one. The database is then on a revision the older tree
does not have, and `alembic upgrade head` would stop with "Can't locate
revision". `gstbot-migrate`'s `ExecCondition` (`deploy/migration_check.py`)
sees that and skips the unit rather than failing it, so the API and worker
that require it still start. `journalctl -u gstbot-migrate` says which revision
the database is on.

The sha can be any commit the box can fetch from `origin` — the deploy key
described under "Releasing" is what makes that work.

To put back only the previous frontend — a release whose UI is broken but whose
API is fine — swap the kept build back in; `gstbot-web` serves whatever `dist`
holds, so no restart is needed:

```sh
/opt/GSTBot/deploy/rollback-frontend.sh    # run it again to undo
```

It checks that `dist.prev` holds a build before moving anything, and refuses
while a deploy holds the lock. (The two `mv` commands it replaces moved the live
build away first, so with no `dist.prev` — a fresh box, or a second rollback —
they left the site with no `dist` at all.)

A release whose `frontend/` is unchanged, with the same `VITE_*` settings,
skips the build and keeps serving the one it has; `frontend/.dist-source`
records what that build was made from.

## Backups

```sh
systemctl list-timers gstbot-backup.timer     # when it last ran, when it next will
journalctl -u gstbot-backup --since -7d       # what happened on each of those nights
ls -lh /var/backups/gstbot                    # what is actually on disk
systemctl start gstbot-backup.service         # take one now, synchronously
```

`gstbot-backup.timer` runs `deploy/backup.sh` at 02:30 with up to 15 minutes of
jitter, and `Persistent=true` catches up a night missed to a reboot. `deploy.sh`
starts the same unit before every migration, so the dumps in that directory are
a mix of nightly ones and one per release. Each run
writes `gstbot-<timestamp>.dump` to `/var/backups/gstbot`, reads it back with
`pg_restore --list` before keeping it, and deletes dumps older than 14 days.
Every dump from the last 24 hours is kept; past that, each day keeps its first
dump and its newest — the state before that day's releases and the state after
them — and the ones in between are thinned. Nothing is deleted by a run that failed, and a dump only takes its final name
once it has been verified — so every `*.dump` in there is one that was
readable at the moment it was written.

The knobs are environment variables with defaults in the script
(`GSTBOT_BACKUP_DIR`, `GSTBOT_BACKUP_RETENTION_DAYS`, `GSTBOT_BACKUP_MIN_FREE_MB`),
which is what makes a restore drill into a scratch directory a one-liner rather
than an edit. The connection details are not among them: the script reads
`DATABASE_URL` from `/etc/gstbot/gstbot.env`, so it cannot end up dumping a
database the application no longer uses.

To restore — into a scratch database first, always:

```sh
sudo -u postgres createdb gstbot_restore --owner gstbot
sudo -u gstbot pg_restore --dbname gstbot_restore --no-owner \
    /var/backups/gstbot/gstbot-20260802T023014Z.dump
```

`--format=custom` means `pg_restore --list` can be filtered down to one table
and fed back with `--use-list`, which is usually what an incident actually
needs. Restoring over the live `gstbot` database is a decision to take with
the stack stopped, not a step to copy from a runbook.

Two limits, repeated here because they are the ones that matter at 3am: the
dumps are on the same disk as the database, and the uploaded invoice files in
`/var/lib/gstbot/invoices` are not in them.

## Monitoring

```sh
systemctl is-failed gstbot-monitor.service    # "is anything wrong" in one command
systemctl start gstbot-monitor.service        # run the checks now, synchronously
journalctl -u gstbot-monitor -n 30            # what the last pass found
systemctl list-timers 'gstbot-*'              # both timers, last and next run
```

`gstbot-monitor.timer` runs `deploy/monitor.sh` every 15 minutes. systemd
already restarts what crashes and the readiness probe already holds traffic
back from an API that cannot reach its database; what neither of them does is
tell anybody. So the checks are the failures that are silent by construction:

| Check | The failure it is for |
|---|---|
| the four running units are `active` | one exhausted `StartLimitBurst` and stopped being restarted |
| `gstbot-backup.timer` is `active` | it was never enabled, or was disabled and not put back |
| a `*.dump` newer than 48 hours exists | dumps have been failing into a journal with no reader |
| 1 GiB free where the dumps go | the disk fills, and it takes out four products |
| `/health/ready` on the bridge | the API is not serving |
| `/health/live` through Caddy | DNS, TLS or `knol-caddy` — the part the bridge check cannot see |
| what `/health/jobs` says | a worker that is running but takes no tasks, the broker unreadable, more than `GSTBOT_MONITOR_MAX_QUEUE_DEPTH` (100) tasks waiting, a scheduled job that has not run on time |
| what `/health` says | the database, Redis or storage reported anything but `ok` |

Both health endpoints answer 200 while degraded, on purpose, so the last two
read the body (`deploy/monitor_health.py` turns it into one problem per line)
rather than the status code.

The last two are separate on purpose: only the public one failing means the
edge, and knowing that before logging in is most of the value.

Every check runs even after one has failed — a report that stops at the dead
API and says nothing about the full disk that caused it is the wrong report.
The unit is left `failed` when anything is wrong, which is what makes
`systemctl is-failed` a complete answer on a box with no alerting configured.

It writes nothing: no `StateDirectory`, no `ReadWritePaths`, and
`ProtectSystem=strict`, so the filesystem is read-only to it. That is also why
it does not deduplicate — there is nowhere to remember what it already said. A
problem that persists is reported every 15 minutes, deliberately: a monitor
that goes quiet after the first alert cannot be told apart from one that
stopped running.

To have it reach somebody, set one variable in `/etc/gstbot/gstbot.env`:

```
GSTBOT_ALERT_WEBHOOK=https://hooks.example.com/...
```

It POSTs `{"text": ...}`, which is the field Slack, Discord and Mattermost
incoming webhooks all read, alongside the problems as a list for anything that
parses the body. Unset — which is how it ships — every check still runs and
still lands in the journal behind a failed unit; the webhook only changes who
finds out without looking.

The thresholds are environment variables with defaults in the script
(`GSTBOT_MONITOR_MAX_BACKUP_AGE_HOURS`, `GSTBOT_MONITOR_MIN_FREE_MB`,
`GSTBOT_MONITOR_READY_URL`, `GSTBOT_MONITOR_PUBLIC_URL`). The backup window is
48 hours rather than 24 because the timer carries 15 minutes of jitter and
catches up after a reboot, so a tighter window reports a dump that is merely
late — and an alert that is usually wrong is one people learn to close.

What it does not do is page anyone, keep history, or notice a trend. It answers
"is something broken right now", which is the question this box did not have an
answer to at all.

## The daily sweep

```sh
journalctl -u gstbot-beat -n 30               # what beat has published
journalctl -u gstbot-worker -g 'deadline sweep' --since yesterday
```

`gstbot-beat.service` runs Celery beat, which publishes two tasks a day:
`alerts.sweep_filing_deadlines` at **07:00 IST**, and `alerts.send_pending_emails`
fifteen minutes after it. The worker executes both. Beat holds only the "when"
— it opens no database connection, which is why it is the one unit here that
does not `Requires=gstbot-migrate.service`.

The sweep reads where each business's returns stand and keeps one alert per
period and return type in step with that. It writes rows; **it sends nothing
itself**. The second task is what emails a digest of each business's open
alerts — and on this box it is a no-op, because `ALERTS_EMAIL_ENABLED` is
unset in `/etc/gstbot/gstbot.env`. No SMTP relay is configured, so every alert
still appears in the product with `channel` staying null. Filling in
`SMTP_HOST` and the credentials in the env file's "Email" section turns it on
without a redeploy — the schedule is already running, waiting for something to
send.

Two operational facts about it:

**Exactly one beat process may run.** Two means two of every scheduled run.
systemd guarantees one instance of one unit and this is a single-host
deployment, so nothing else is needed — but the day a second box appears, the
schedule does not move with it without a lock, and there is none.

**It keeps a file.** `/var/lib/gstbot/celerybeat-schedule` is beat's record of
when each entry last fired, and it is the only state on this box outside
Postgres and the uploaded invoices. It is not in the backups and does not need
to be: deleting it while beat is stopped costs at most one duplicate run, and
the sweep is idempotent — it recomputes the day's alerts from the returns
table, so running it twice, or not at all, converges the next morning.

A missed run is not made up. There is no catch-up on purpose: a box that was
down overnight would otherwise fire the sweep on boot alongside everything else
it deferred, and tomorrow's run is the one that matters.

## What is deliberately not here

**Off-host copies of the backups, and the invoice files.** The nightly dump
below covers the database and lands on the same disk as the database. That is
the cover for a bad migration or a mistaken delete; it is not cover for losing
the box, and nothing here copies `/var/backups/gstbot` anywhere else.
`/var/lib/gstbot/invoices` — the uploaded originals, under the same statutory
retention as the rows that point at them — is not dumped at all. A restore
gives back every row, including the paths of files that are no longer there.

**Isolation from the other products.** Postgres, Redis and the edge are shared.
A `FLUSHALL`, a runaway connection count, or a bad `/opt/knol/Caddyfile` edit
takes out more than GSTIndia. That is a trade the box was already making before
this app arrived; it is worth knowing rather than discovering.
