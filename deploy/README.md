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
bridge and `/health/live` through Caddy. Last, `deploy/services_settled.sh`
waits for a Celery worker to answer a ping and, after two restart intervals,
requires every restarted unit to be active with no automatic restarts. The
units restart themselves, so a worker or beat that dies on start still reads
"active" between deaths, and nothing else asks them. Anything that fails stops
the release, and "Deployed <sha>" is printed only after all of it.

The frontend is built into `frontend/dist.next`, beside the `dist` the site is
serving, and swapped in only once it has produced an `index.html`; the build it
replaces is kept as `frontend/dist.prev`. A build that fails therefore stops the
release with the previous site still up, rather than an emptied `dist`.

**Prefer building the frontend somewhere else.** This box has 8 GB shared by
every product on it, and a build here can swap it to a halt — on 2026-10-29 one
did, and was killed with the release half-done. Build `frontend/` from the
commit being released on a machine with the memory, write
`<git rev-parse HEAD:frontend>-<vite hash>` to `dist/.source` (the vite hash is
the first 16 hex digits of the sha256 of the `VITE_*` lines in
`/etc/gstbot/gstbot.env`), and rsync `dist/` to `frontend/dist.upload/` before
running the script. The release stages that upload exactly as it would its own
build, and discards one built from any other tree. With no upload it builds
here only if `GSTBOT_BUILD_MIN_FREE_MB` (1536 by default) is free, and otherwise
stops before touching anything.

The release also refuses to start unless `GSTBOT_DEPLOY_MIN_FREE_MB` (1024 MiB
by default) is free on the disk holding `/opt/GSTBot`: it reinstalls the
virtualenv in place under the running services, and an install that runs out of
space halfway leaves them on a half-upgraded environment.

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

Dependabot only sees the floors, never the transitive pins that make up most of
the lock, so `.github/workflows/audit.yml` runs `pip-audit` against the lock
exactly as written, and `npm audit` against the frontend's production packages,
every Monday and from the Actions tab on demand. It is not a pull-request gate:
a red run is the report, and recompiling the lock is the fix.

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
`RAZORPAY_WEBHOOK_SECRET` is set) and `email` (every email the product sends —
alert digests, subscribers' deadline reminders, password-reset links:
`ALERTS_EMAIL_ENABLED` and `SMTP_HOST`). `unconfigured` or `disabled` there is
a feature switched off, not a fault, and does not change `status`;
`misconfigured` (email switched on with no `SMTP_HOST`; Razorpay keys with no
webhook secret, which refuses every renewal and refund it reports, or a key id
with no secret) is a mistake to fix, and the monitor reports it.

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

Each run also snapshots the uploaded originals (`UPLOAD_DIR`) into
`uploads-<timestamp>/` beside the dump, with `rsync --link-dest` against the
previous snapshot, so an unchanged file is a hard link rather than another copy.
Snapshots are kept and thinned exactly as the dumps are. To restore one, copy it
back over `UPLOAD_DIR` (`rsync -a uploads-<timestamp>/ /var/lib/gstbot/invoices/`)
alongside the dump of the same moment.

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
| no release has held `/run/lock/gstbot-deploy.lock` for over 30 minutes (a run during a shorter one stands down instead of reporting the restart) | a release hung partway, with services stopped or half-upgraded |
| `gstbot-backup.timer` is `active` | it was never enabled, or was disabled and not put back |
| a `*.dump` newer than 48 hours exists | dumps have been failing into a journal with no reader |
| an `uploads-*` snapshot newer than 48 hours exists (when `UPLOAD_DIR` does) | the snapshot of uploaded invoices fails after the dump, so the dump alone stays fresh |
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

The same switch carries two things that have no in-app fallback, so "off" is not
free: the daily `subscriber-deadline-reminders` task (08:00 IST), which emails
the people who signed up on the public site three days before each GSTR-1 and
GSTR-3B due date, and the password-reset link `/forgot-password` sends. With
email off, subscribers get nothing and a forgotten password cannot be reset —
the reset page still says a link is on its way, because it must not reveal which
addresses have accounts.

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
retention as the rows that point at them — is snapshotted beside the dumps (see
"Backups"), on the same disk, so it shares their limit: cover for a mistaken
delete, not for losing the box.

**Isolation from the other products.** Postgres, Redis and the edge are shared.
A `FLUSHALL`, a runaway connection count, or a bad `/opt/knol/Caddyfile` edit
takes out more than GSTIndia. That is a trade the box was already making before
this app arrived; it is worth knowing rather than discovering.

## GST marketing frontend release — 2 November 2026

The marketing-only release is based on deployed commit `482f1c5`. It changes the
landing page and its tests: accurate return-preparation language, a real link to
`https://doaide.com/demo/`, removal of unverified endorsements/customer counts,
and a secondary link to `https://doaide.com/company/`. Existing tool, login,
pricing and guide routes remain intact. The main marketing site is a separate
Cloudflare Pages project (`DoAideAi/products-site`), not this server's Caddy route.

Validation: all 4,642 frontend tests, the backend pytest suite and backend ruff
check pass. Frontend lint has zero errors and four pre-existing warnings.
The local production build prerenders all 1,134 routes. Chrome checks cover the
landing page at desktop/mobile widths, demo/app destinations, calculator and
sign-in rendering. The demo flow prepares an email; it does not confirm a booking.

This release is built off-server with `npm ci` and `npm run build`. Production
has no `VITE_*` overrides (SHA-256 prefix `e3b0c44298fc1c14`). The built tree is
uploaded separately, checked against the committed frontend tree, and assigned
root ownership with read-only access for other users. Linux `renameat2` with
`RENAME_EXCHANGE` swaps the ready tree and live `frontend/dist` atomically; the
previous complete tree remains at the staging path for rollback. Old hashed
assets are retained in the new tree for visitors who already have a tab open.

No database migration or API/worker/web restart is necessary for these static
file changes. The running API continues to report its previous release revision.
The server checkout advances only by a fast-forward after verifying the original
revision and a clean worktree. Record the new frontend tree id in
`frontend/.dist-source`; restore its previous value along with the retained tree
if rolling back. A full backend deployment still follows the normal runbook above.

## GST visual refresh — 2 November 2026

The next frontend-only release starts from `c5ef02e` and adopts the main site's
Inter typography, teal palette and nine-dot brand mark. The homepage has a
focused GSTIN lookup and a searchable, category-filtered directory: six common
tools appear initially, with the full catalogue available through search and
All tools. Repeated promotions, news and the scrolling banner leave the homepage.
Shared tool, account and pricing styles follow the same light/dark theme. Public
pricing gains navigation and a styled billing-period control. Calculator,
authentication, subscription and API behaviour remain the same.

Validation: 4,643 frontend tests and 7,974 backend tests pass (11 backend skips).
Backend ruff passes; frontend lint has zero errors and four existing warnings.
The production build prerenders all 1,134 routes. Chrome checks cover widths
360, 390, 768 and 1440, search/filter/reset, GSTIN routing, calculator results,
sign-in, monthly/annual pricing and persisted dark mode. Local pricing visual
checks use the public production pricing response; no checkout is submitted.

The existing frontend coverage ratchet still fails. A clean `c5ef02e` baseline
with the same dependencies and Node 24 also fails (93.29% statements, 90.44%
branches, 88.30% functions, 95.83% lines); the refreshed landing's coverage
improves. No coverage threshold or exclusion is changed for this visual release.

Use the same off-server build and locked atomic frontend swap described above.
Retain old hashed chunks for open tabs and the previous complete tree under
`/var/backups/gstbot/frontend-pre-ui-<revision>`. Store the old/new frontend
source IDs and rollback tree in `frontend-ui-<revision>.json` in that directory.
Do not run the full backend deploy script for this release.

## Google account linking — 2 November 2026

Google's callback previously reported `account_deactivated` for an active,
password-created account with the same email. Automatic merging remains refused:
an unverified email entered at registration does not prove ownership. A verified
Google callback now offers `/auth/link-google`, where the existing GST password
must be confirmed once. Successful linking preserves the user, business, role,
password and books; subsequent Google sign-ins resolve the stored Google subject.

The pending proof lives in the signed HttpOnly session for five minutes, bound
to the OAuth client, user and current password. The POST requires a CSRF nonce
and the password, with both IP and account attempt limits. A conditional update
and the identity uniqueness constraint reject replay, competing links and
concurrent password resets. No database migration or OAuth credential change is
needed. Accounts already connected to another provider are not overwritten.

Build the frontend off-server, retain the prior tree and cached hashed assets,
and deploy the matching backend source under the deployment lock. Update
`backend/.release` and restart only `gstbot-api` after the frontend swap. Verify
readiness, the worker probe and service restart count. A direct request to
`GET /api/v1/auth/google/link` without the browser proof must return 400 and
`Cache-Control: no-store`. Rollback restores the previous source, complete
frontend tree, `.dist-source` and `.release`, then restarts the API. Retain the
release record at `/var/backups/gstbot/google-link-<revision>.json`.

Browser verification covers desktop/mobile layout, password error recovery and
expired-proof recovery. Automated integration tests exercise successful linking,
preserved account data, later Google sign-ins, wrong passwords, CSRF, tampered or
replayed cookies, expiration, deactivation, client/password changes, concurrent
resets and attempt limits. A real Google account holder still completes the
one-time password confirmation in their own browser.

## Free introductory pilot — 2 November 2026

Owners can start one 60-day pilot from Pricing: 20 lifetime SMB places and 10
lifetime CA-firm places. SMB covers the home registration; CA covers up to five
registrations including the home registration. Additional registrations must
already be accessible through a live owner/accountant membership. Coverage never
creates a membership, and unlinking a client does not recycle a place. Each
registration receives 500 invoice uploads per calendar month, counting deleted
uploads. Existing configured daily AI limits continue to apply.

Pilot entitlements are separate from paid subscriptions and payment history.
Active paid plans take precedence. No payment details, order, mandate or charge
is created. Expiry uses UTC timestamps on every access check, without a cron
job; Pricing shows the end date in India time. The business returns to its
ordinary free allowance unless it explicitly buys a plan. Existing account data
and reconciliation reports created before the pilot ended remain exportable.
Regular prices remain SMB ₹499/month and CA ₹2,999/month. With no Razorpay key
configured, the paid-upgrade CTA requests help through the main site's demo
page instead of opening an unavailable checkout.

Migration `0029` adds `pilot_enrollments` and `pilot_businesses`. It changes no
existing table or customer row. PostgreSQL transaction advisory locks serialize
admission/coverage; unique and check constraints enforce account, business and
cohort limits. Never reset pilot dates or delete coverage to reuse a place.

Build off-server and verify the frontend manifest and source marker. Take a
fresh `gstbot-backup.service` dump and uploaded-file snapshot before migration.
Under `/run/lock/gstbot-deploy.lock`, fast-forward the clean server checkout,
run `systemctl restart gstbot-migrate.service`, then atomically exchange the
frontend trees and update `.dist-source` and `backend/.release`. Restart the API
and worker (both depend on the migration unit), web and beat. Verify migration
0029, live readiness/jobs, public pricing, authenticated-route rejection and
settled service restart counts. Keep prior hashed assets for open browser tabs.
Record the backup and rollback tree in
`/var/backups/gstbot/free-pilot-<revision>.json`.

Rollback restores source, frontend and release markers and restarts the services.
Leave the additive pilot tables in place: downgrading could destroy enrollments
made after release. The prior application ignores those tables. Existing tests
cover payment/tenant behavior; new tests exercise admission, retries, limits,
expiry, paid-plan precedence, report exports and membership boundaries. Chrome
checks exercise public/login/active/expired screens at 360, 390 and 1440 pixels
with local API fixtures; no real customer's pilot is started for verification.

## GST landing-page brand alignment — 2 November 2026

This frontend-only update starts from `8061362`. The homepage follows the current
doaide.com design: a 64px header, dark primary buttons, gradient headline, subtle
hero grid, consistent card spacing and a branded footer. Mobile navigation is
collapsible, closes on selection or Escape, and restores toggle focus on Escape.
The scoped `landing.css` prevents legacy styles from centering tool-card content
or constraining the final call to action. Existing tools and pilot terms remain.

Validation: 4,662 frontend tests pass; lint has zero errors and the four existing
warnings. All 1,134 routes prerender successfully. First-load assets remain under
the 140KB gzip budget. Browser checks cover 320, 390, 768, 980 and 1440px, both
themes, mobile-menu layout and keyboard dismissal, search, filters and FAQs.

Use the existing off-server build and locked atomic frontend exchange. Verify
the clean production checkout and source marker before publishing; retain old
hashed assets and the previous complete tree. Record both source markers and
the rollback tree in `/var/backups/gstbot/landing-brand-<revision>.json`.
No database migration, environment change or service restart is required.

## GST signed-in workspace alignment — 3 November 2026

This frontend-only release starts from `1a20389` and extends the landing-page
design to the authenticated workspace. A compact brand header and grouped
sidebar replace the overflowing navigation row. The same navigation becomes a
scrollable drawer on smaller screens. Business selection stays in the header;
account export and sign-out are in the sidebar. Cards, tables, forms, primary
buttons and light/dark themes use the shared brand tokens. Help controls sit
below the content so they do not cover financial figures or table actions.

Authenticated pricing now retains the workspace shell and active registration.
Public pricing remains accessible without signing in. Dashboard and password
form changes are presentational; no API, authentication or financial calculation
changes are included.

Validation: 4,666 frontend tests pass, including current-page drawer dismissal
and signed-in/public/loading pricing routes. Lint has zero errors and four
existing warnings. The build prerenders all 1,134 routes and remains below the
140KB first-load gzip budget. Browser checks use isolated sample API responses
for all 11 workspace routes at 320, 390, 768, 1024 and 1440px, plus mobile and
desktop dark mode. No real account or business data is changed by these checks.

Publish using the existing off-server build and locked atomic frontend exchange,
retaining prior hashed assets and the previous tree. Store release metadata in
`/var/backups/gstbot/workspace-brand-<revision>.json`. No database, environment or
service restart is needed; the backend release marker remains unchanged.

## GST login alignment and unavailable SSO recovery — 3 November 2026

The login page now uses the landing page's brand header, grid/glow treatment,
navy primary action and shared light/dark colours. `/login` opens on sign in;
`/login?mode=register` opens registration, and both remain available in the form.
Password visibility, validation, GSTIN entry and password recovery remain usable
on mobile. The provider buttons read `/api/v1/auth/providers`, so a disabled
provider is not advertised and enabling one does not require a frontend rebuild.
A failed provider lookup can be retried without blocking email sign-in.

Old browser links to an unconfigured OAuth provider now redirect to
`/login?error=<provider>_unavailable` with an explanation and working alternatives.
API requests retain the documented 501 response. Existing OAuth state, token,
email verification and account-linking rules are unchanged.

Validation: 4,677 frontend tests and 8,063 backend tests pass (11 backend skips).
Both linters have no errors; frontend lint retains four existing warnings.
Browser checks cover sign-in, registration, GSTIN validation, password visibility,
provider availability/retry and Microsoft errors at 320, 390, 768, 1024 and 1440px
in light and dark mode, using isolated sample API responses.

At diagnosis, production had Google configured and neither Microsoft credential
set. The available Azure CLI session was expired. Microsoft activation requires
an authenticated Entra administrator to configure the application and place
`MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET` in the protected server
environment. Never commit or paste the secret into chat. The Web redirect URI
must be `https://gst.doaide.com/api/v1/auth/microsoft/callback`. Verify the complete
provider round trip with an account holder before calling Microsoft enabled;
the unavailable-provider recovery alone does not activate Microsoft sign-in.

Build off-server and publish the matching frontend and backend source under the
existing deployment lock, retaining old hashed assets. Update `.dist-source`
and `backend/.release`, then restart only `gstbot-api`. No dependencies, database
migrations or environment changes are required for this release. Check readiness,
the browser redirect and API 501, Google initiation, and service restart counts.
Rollback restores the source, frontend tree and both release markers before
restarting the API. Save metadata in
`/var/backups/gstbot/login-brand-<revision>.json`.

## Metricool website connection — 3 November 2026

Metricool brand `7824654` uses tracking hash
`36195e51b9aa7f88d328d9d285bb8be`, confirmed against the connected account.
The local JavaScript adapter sends the same `c3po.jpg` image request as the
provided `be.js` tag, retaining the brand, page URL and viewport dimensions.
The vendor tag copies the complete URL/referrer; the adapter sends only public
paths from the sitemap and known HSN/product pages, and only the external
referrer's origin. Query strings, fragments, GSTIN lookup identifiers, auth and
workspace routes are excluded. Signed-in users, local previews and prerendering
do not send visits. SPA navigation records a new page view without requiring a
document reload; StrictMode does not double-count the initial visit.

Only `https://tracker.metricool.com` is added to the SPA's `img-src`. No inline
script, extra script origin, cookie or backend change is needed. Build off-server
and deploy the frontend with the existing locked atomic exchange. Update only
the GST site's `img-src` in the shared Caddyfile, preserving all other sites and
directives. Validate the candidate, reload Caddy without a restart, then verify
the public CSP and a real Metricool beacon. Retain the prior Caddyfile securely
alongside the previous frontend and release metadata for rollback. The API
release marker stays unchanged.

## GST Action Agent — 3 November 2026

The signed-in `/action-agent` page creates a read-only plan for a selected period.
It calls `POST /api/v1/action-agent/review` with a period and one of three review
focuses. The current tenant is resolved through the ordinary session and
`X-Business-Id` membership checks; the model cannot supply a tenant or period to
a tool. Viewers may request a review because no business records are written.

Set `OPENAI_API_KEY` in `/etc/gstbot/gstbot.env` using the server's secret handling;
never place it in a frontend variable or source control. `OPENAI_AGENT_MODEL`
defaults to `gpt-5.4-mini`. The Responses API is called directly with existing
httpx; no dependency install or schema migration is required. Keep provider
responses out of error logs. Only period totals, filing status, reconciliation
counts and validator field/severity counts are sent. Invoice text, supplier
names, GSTINs, contact details and documents are excluded. The page describes
this use before the user starts a review. `store: false` disables Responses
application-state storage; it is not a claim of zero provider retention.

The agent may call only `check_reconciliation` and `check_invoice_quality`.
Checks are required for the selected focus. At most three provider requests,
2,200 output tokens each, run inside a 55-second network-workflow deadline.
Invoice validation above 2,000 records is explicitly skipped and directs the
user to Filing. Model outputs are validated against a fixed schema; navigation
uses a local destination allowlist. No messages are sent, invoices edited or
returns filed. AI advice is presented with sources and review guidance.

The normal Redis-backed limiter allows three reviews per minute and ten per day
per authenticated account, with a shared 200/day site limit. Overrides use
`action_agent_minute`, `action_agent_daily` and `action_agent_site_daily`.
Like existing limits, Redis failure falls back to per-process counters; these
are request controls, not a provider billing cap. Three provider failures open
a 120-second breaker. Missing credentials and provider failures return a usable
503 without interrupting the rest of the product.

Build off-server and publish the frontend and backend source together under the
existing deployment lock. Retain the old frontend, source revision, backend
release marker, and a root-only backup of the environment file. Install the key,
update `.dist-source` and `backend/.release`, and restart only `gstbot-api`.
Verify readiness, anonymous refusal, UI navigation, and a synthetic OpenAI review
without reading customer data. Rollback restores those files and restarts the
API. The production database and shared Caddyfile require no changes.

Validation includes a real OpenAI review using synthetic records, tenant and
switched-business isolation, denied tool arguments, no database writes, provider
failures, rate limits, cancellation and mobile/light/dark browser checks. The
frontend coverage gate already fails on the prior release (`4b4a932`): 95.72%
lines against 99%, despite all tests passing. This release leaves the thresholds
unchanged; fixing the repository-wide coverage gap is separate work.


## CA purchase-data and review workflows — 3 November 2026

This release adds `/purchase-import`, `/client-access`, `/join`, `/clients` and
`/review/:runId`. Purchase registers accept invoice-level UTF-8 CSV or one-sheet
XLSX, limited to 5 MB and 2,000 rows. Mapping and row validation precede explicit
commit; invalid rows require an explicit skip choice. Existing duplicates are
skipped, repeated rows within the file are refused, and monthly allowances are
checked atomically using the ordinary upload lock. Credit notes, formulas and
multi-line invoice grouping are not supported by this importer. Saved mappings
belong to the selected business. No AI service processes these imports.

Owners create seven-day, single-use invitation links for accountant/viewer
access. The owner copies and shares a link manually; the app sends no invitation
email. Only token hashes are stored. Acceptance requires the invited login email
and a still-authorized inviting owner. Reissuing invalidates earlier pending
links. Roles and revocation apply to linked memberships; invitation acceptance
does not allocate pilot capacity or extend trial terms. The switcher's password
linking form is replaced with invitation management; its older API remains for
compatibility with existing same-person accounts.

Finding reviews preserve the original reconciliation and append actor/version
history. A resolved finding needs a confirming decision and evidence note.
Disagreements require correcting the source and reconciling again. Changed
sources or a newer run prevent completing/exporting an old review. Whole-report
approval and reviewed CSV export are explicit; export uses the existing
pilot/report entitlement and escapes spreadsheet formulas. The dashboard's last
onboarding step completes only after a current reviewed report is exported.
The client queue only lists businesses the login can access, with unknown
exception counts left unknown until reconciliation. Copy no longer advertises
bulk portal filing or a native Tally export. Pilot limits and prices are unchanged.

Migration `0030` creates six tables and their indexes; it does not rewrite old
customer rows. Back up the database using `gstbot-backup.service` before applying
it with `gstbot-migrate.service`. Build the frontend off-server, verify the
artifact manifest and source fingerprint, and publish source plus static files
under `/run/lock/gstbot-deploy.lock`. Restart only `gstbot-api`, retain old hashed
assets, and allow Caddy's 30-second health check to recover before public probes.
No dependency install, secret update or Caddy change is needed.

Rollback restores the preceding application source, backend release marker and
static tree. Leave the additive `0030` tables and Alembic revision in place:
downgrading would erase any reviews or invitations created after launch. Restore
a database backup only through a separately reviewed recovery procedure.

Validation covers tenant/role boundaries, switched-business writes, invitation
expiry and single use, atomic quotas, review version conflicts and invalidation,
the real import-to-reconciliation-to-reviewed-export workflow, and PostgreSQL
migration/schema/rollback checks. Browser checks use synthetic local accounts;
no production customer records or pilot places are used for testing. The
repository's existing coverage thresholds remain unchanged; record their actual
result separately from functional test results.


Release checks: the full backend run passed 8,382 tests (12 skipped), followed by
33 focused import/review tests including 17 added financial-input cases. All
4,754 frontend tests passed. PostgreSQL passed 54 migration tests and the actual
import/reconcile/review/export and invitation/revocation flows. Desktop/mobile
and light/dark browser checks passed. The build prerendered 1,134 routes; first
load is 121.1 KB gzipped against a 140 KB budget. Coverage gates are not green:
backend combined coverage is 97.19% against 99%; frontend lines are 94.49%,
statements 92.12%, branches 89.37% and functions 86.28%, below their thresholds.
The preceding frontend release was already below its gate; this change reduces
the measured frontend percentages further. No threshold was lowered.

## Acquisition fixes — 3 November 2026

`POST /api/v1/feedback/demo` validates and saves demo requests in the existing
operator inbox at `/admin/feedback`. Only approved administrators can read it;
the public response contains only a reference. Rate limit: five requests per
hour per IP. No migration or new mail service. SMTP is not configured on
production, so check the inbox for new requests. A request is not an appointment.

Add `https://doaide.com,https://www.doaide.com` to `BACKEND_CORS_ORIGINS`, keeping
`https://gst.doaide.com` first. Update only the GST site's CSP from
`deploy/caddy-gstbot.conf`; production was missing the existing Razorpay
allowances. Validate and reload Caddy, never restart the shared proxy.

`frontend/public/ads.js` must match the marketing repository's `assets/ads.js`.
It uses Google Ads account 952-322-4323 / AW-18552515324 and five explicit
conversion labels from that account. Measurement is disabled until consent;
consent is shared on the parent domain. No automatic enhanced conversions or
ad personalization. No token-bearing auth URL is tagged; a completed OAuth
signup is queued for the next page. URL queries, fragments and private record
paths are excluded from ad events. Failed forms/uploads, empty reconciliations,
checkout clicks and free pilots never count as paid revenue. Verified payments
carry the order reference and actual INR amount, deduplicated by transaction ID.

Publish the local frontend build and matching source under the deployment lock,
checking that production is still the expected parent commit. Retain the previous
frontend tree, backend release marker, CORS configuration and GST CSP. Back up the
database before deployment. Restart only the API; the static server reads the
new files. Rollback restores those retained artifacts and the prior source.
No campaign or advertising budget is created by this release.
