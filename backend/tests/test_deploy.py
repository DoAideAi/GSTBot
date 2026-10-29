"""Checks over the deployment manifests in ``deploy/``.

None of this runs on the server, so nothing here can prove the deployment
works. What it can prove is that the files agree with each other and with the
application — which is where this class of configuration actually goes wrong.
A port changed in a unit and not in the site block, an upload limit raised in
the env file past what the edge will accept, a module path that was renamed in
``app/`` months after the ``ExecStart`` line was written: each of those is
silent until a deploy, and each is a string comparison here.

The other half is the production configuration itself. ``gstbot.env.example``
is fed through the real ``Settings`` model, so the template ships in a state
that boots cleanly and logs no warnings — and the assertion that it does is
the same code path the server runs.

What makes this deployment unusual, and what most of the cross-checks below
exist for: **the box is shared**. Caddy is a container belonging to another
product, Postgres and Redis are shared clusters, and the ports are allocated
across four applications. So the failure mode is not only "GSTIndia is
misconfigured" but "GSTIndia collides with something already running" — a
duplicated Redis database, a port another product owns, a bind address the
containerised edge cannot reach. Those are the assertions with teeth here.
"""
from __future__ import annotations

import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, validate_startup_config

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "deploy"
SYSTEMD = DEPLOY / "systemd"

# A *site block*, not a Caddyfile. The edge on this host is `knol-caddy`, a
# container shared with the other products on the box, configured from one
# file (/opt/knol/Caddyfile) that this block is appended to. It happens to be
# a valid standalone Caddyfile as well, which is what lets CI parse it.
SITE_CONF = DEPLOY / "caddy-gstbot.conf"
ENV_EXAMPLE = DEPLOY / "gstbot.env.example"
DEPLOY_SCRIPT = DEPLOY / "deploy.sh"
BACKUP_SCRIPT = DEPLOY / "backup.sh"
MONITOR_SCRIPT = DEPLOY / "monitor.sh"
STATIC_SERVER = DEPLOY / "static-server.mjs"
TARGET = SYSTEMD / "gstbot.target"

# Where the nightly dump lands. Written out for the same reason SITE is: the
# unit and the script agreeing is only worth asserting if they agree on a
# directory the runbook also tells someone to create.
BACKUP_DIR = "/var/backups/gstbot"

# The four units that run Python out of the deployed virtualenv.
PYTHON_UNITS = (
    "gstbot-migrate.service",
    "gstbot-api.service",
    "gstbot-worker.service",
    "gstbot-beat.service",
)
# gstbot-web runs node, so it shares the sandbox and none of the Python
# plumbing. Kept apart rather than special-cased inside each test, so that the
# checks that are about "every unit" really are about every unit.
SERVICE_UNITS = (*PYTHON_UNITS, "gstbot-web.service")
# The units that stay up, as opposed to the one-shot migration. gstbot-beat
# serves nobody, but everything asserted of this group — Restart=always, a
# start limit in the section systemd reads it from — is about a process that is
# supposed to still be running tomorrow, which it is.
SERVING_UNITS = (
    "gstbot-api.service",
    "gstbot-web.service",
    "gstbot-worker.service",
    "gstbot-beat.service",
)
# Where beat keeps its record of when each entry last fired. Under the
# StateDirectory because /opt is read-only to these units; written out here
# because the runbook tells someone to delete this file, and a path that only
# exists in an ExecStart is one the runbook can drift away from.
BEAT_SCHEDULE_FILE = "/var/lib/gstbot/celerybeat-schedule"
# The nightly dump. Kept out of SERVICE_UNITS because almost nothing that is
# true of the four above is true of it: it is not in gstbot.target, it has no
# [Install] section, and it runs a shell script rather than the application.
# What it does share is the sandbox and the service account, which is what
# SANDBOXED_UNITS below is for.
BACKUP_SERVICE = "gstbot-backup.service"
BACKUP_TIMER = "gstbot-backup.timer"
# The periodic health check. Kept apart from the units above for the same
# reasons as the backup, and from the backup because it writes nothing — the
# one unit here with no writable path at all.
MONITOR_SERVICE = "gstbot-monitor.service"
MONITOR_TIMER = "gstbot-monitor.timer"
# Every unit that runs as the service account under the shared sandbox.
SANDBOXED_UNITS = (*SERVICE_UNITS, BACKUP_SERVICE, MONITOR_SERVICE)
# The two units nothing starts on its own: each is enabled by hand and would
# otherwise be installed, never run, and never missed.
TIMER_UNITS = (BACKUP_TIMER, MONITOR_TIMER)

# The one address this deployment answers on. Written out rather than derived,
# because "the site block and the CORS list agree" is only interesting if they
# agree on the right thing.
SITE = "gst.doaide.com"

# The Docker bridge gateway. Both host processes bind it: reachable from the
# Caddy container, and not routed from the internet. See gstbot-api.service.
BRIDGE = "172.18.0.1"
# The Caddy container's own address on that bridge — the only peer whose
# X-Forwarded-* the API honours.
EDGE = "172.18.0.13"

# Where the tree lives on the server.
INSTALL_ROOT = "/opt/GSTBot"

# Redis databases on the shared instance. The README records who owns the
# others; these three are ours and must stay distinct from each other.
FOREIGN_REDIS_DBS = {0, 1, 3, 4, 5}

# Directives that make the unit's sandbox a sandbox. Asserted as a set across
# every unit rather than one by one: they run as the same user under the same
# supervisor, so a directive present on three units and missing from the
# fourth is an oversight, and that is the shape this catches.
HARDENING = {
    "NoNewPrivileges": "yes",
    "PrivateTmp": "yes",
    "PrivateDevices": "yes",
    "ProtectSystem": "strict",
    "ProtectHome": "yes",
    "ProtectProc": "invisible",
    "ProtectClock": "yes",
    "ProtectHostname": "yes",
    "ProtectKernelTunables": "yes",
    "ProtectKernelModules": "yes",
    "ProtectKernelLogs": "yes",
    "ProtectControlGroups": "yes",
    "RestrictNamespaces": "yes",
    "RestrictRealtime": "yes",
    "RestrictSUIDSGID": "yes",
    "LockPersonality": "yes",
    "SystemCallArchitectures": "native",
    "SystemCallFilter": "@system-service",
    "CapabilityBoundingSet": "",
    "AmbientCapabilities": "",
}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_unit(text: str) -> dict[str, list[tuple[str, str]]]:
    """A systemd unit as ``{section: [(key, value), ...]}``.

    A list rather than a dict because systemd does not treat repeated keys
    uniformly — ``Environment=`` accumulates while ``User=`` is last-wins —
    and flattening here would hide the difference from the checks below.

    Backslash continuations are joined, which is the only reason this cannot
    be ``configparser``: the ``ExecStart`` lines wrap.
    """
    sections: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    pending = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not pending and (not line or line[0] in "#;"):
            continue
        if pending:
            line = f"{pending} {line}"
            pending = ""
        if line.endswith("\\"):
            pending = line[:-1].strip()
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, [])
            continue
        assert current is not None, f"key outside any section: {line!r}"
        key, _, value = line.partition("=")
        sections[current].append((key.strip(), value.strip()))

    assert not pending, "unit ends with a dangling line continuation"
    return sections


def entries(unit: dict, section: str, key: str) -> list[str]:
    return [v for k, v in unit.get(section, []) if k == key]


def entry(unit: dict, section: str, key: str) -> str:
    """The effective value of a last-wins directive."""
    found = entries(unit, section, key)
    assert found, f"[{section}] {key}= is missing"
    return found[-1]


def matched(pattern: str, text: str, *, flags: int = 0) -> re.Match[str]:
    """``re.search`` that fails the test rather than returning ``None``.

    Every search in this file is over a config file that is supposed to
    contain the thing being searched for, so a miss is the finding — and
    ``AttributeError: 'NoneType' has no attribute 'group'`` is a poor way to
    report it.
    """
    found = re.search(pattern, text, flags)
    assert found is not None, f"no match for {pattern!r}"
    return found


def parse_env_file(text: str) -> dict[str, str]:
    """``KEY=value`` lines, as systemd's ``EnvironmentFile=`` reads them."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        assert sep, f"not a KEY=value line: {line!r}"
        values[key.strip()] = value.strip()
    return values


def redis_db(url: str) -> int:
    """The database number from a ``redis://host:port/N`` URL."""
    return int(matched(r"redis://[^/]+/(\d+)\s*$", url).group(1))


@pytest.fixture(scope="module")
def site_conf() -> str:
    return SITE_CONF.read_text()


@pytest.fixture(scope="module")
def env_example() -> dict[str, str]:
    return parse_env_file(ENV_EXAMPLE.read_text())


@pytest.fixture(scope="module")
def units() -> dict[str, dict]:
    names = (*SANDBOXED_UNITS, *TIMER_UNITS)
    return {name: parse_unit((SYSTEMD / name).read_text()) for name in names}


@pytest.fixture(scope="module")
def api_block(site_conf) -> str:
    """The ``handle @api { ... }`` body."""
    return matched(r"handle @api \{(.*?)\n\t\}", site_conf, flags=re.S).group(1)


@pytest.fixture(scope="module")
def spa_block(site_conf) -> str:
    """The catch-all ``handle { ... }`` body that fronts the SPA server."""
    return matched(r"\n\thandle \{(.*?)\n\t\}", site_conf, flags=re.S).group(1)


def settings_from(values: dict[str, str], **overrides: str) -> Settings:
    """Build the real Settings from an env-file mapping.

    ``_env_file=None`` stops pydantic-settings reading the repository's own
    ``.env``, and init kwargs outrank ``os.environ``, so what comes back is the
    template and nothing else — not the suite's own test configuration.
    """
    merged = {k.lower(): v for k, v in {**values, **overrides}.items()}
    return Settings(_env_file=None, **merged)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# The files exist and parse
# ---------------------------------------------------------------------------

class TestTheManifestsAreThere:
    @pytest.mark.parametrize(
        "path",
        [
            SITE_CONF,
            ENV_EXAMPLE,
            DEPLOY_SCRIPT,
            BACKUP_SCRIPT,
            MONITOR_SCRIPT,
            STATIC_SERVER,
            TARGET,
            DEPLOY / "README.md",
        ],
        ids=lambda p: p.name,
    )
    def test_a_manifest_exists(self, path):
        assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is missing"

    @pytest.mark.parametrize("name", SERVICE_UNITS)
    def test_a_unit_exists_and_parses(self, name):
        unit = parse_unit((SYSTEMD / name).read_text())
        assert set(unit) == {"Unit", "Service", "Install"}

    def test_the_target_declares_every_service(self):
        target = parse_unit(TARGET.read_text())
        wanted = " ".join(entries(target, "Unit", "Wants")).split()
        assert set(wanted) == set(SERVICE_UNITS)

    def test_no_unit_ships_without_being_declared(self):
        # The other direction. A unit file added to deploy/systemd/ and not
        # added to SERVICE_UNITS is one that nothing above checks — it would
        # be installed by the README's `install deploy/systemd/*` and then
        # never enabled, or enabled and never hardened.
        #
        # gstbot-backup.service is named separately rather than folded into
        # SERVICE_UNITS: it is started by its timer and belongs to no target,
        # so the checks above about gstbot.target would be wrong about it.
        shipped = {p.name for p in SYSTEMD.iterdir() if p.suffix == ".service"}
        assert shipped == {*SERVICE_UNITS, BACKUP_SERVICE, MONITOR_SERVICE}

    def test_every_timer_starts_a_unit_that_ships(self):
        # A timer naming a unit that does not exist is enabled without
        # complaint and fires into nothing, once a night, silently.
        for path in SYSTEMD.glob("*.timer"):
            started = entry(parse_unit(path.read_text()), "Timer", "Unit")
            assert (SYSTEMD / started).is_file(), f"{path.name} starts a missing {started}"

    @pytest.mark.parametrize("name", SERVICE_UNITS)
    def test_a_unit_installs_into_the_target(self, name, units):
        # Both halves are needed and they do different things: WantedBy is what
        # `systemctl enable` writes, PartOf is what makes `systemctl restart
        # gstbot.target` reach this unit. A unit with only the first starts
        # with the stack and then never restarts with it again.
        assert entry(units[name], "Install", "WantedBy") == "gstbot.target"
        assert entry(units[name], "Unit", "PartOf") == "gstbot.target"

    @pytest.mark.parametrize("name", SANDBOXED_UNITS)
    def test_a_unit_is_identifiable_in_a_shared_journal(self, name, units):
        # journald on this box carries four products. Without an explicit
        # identifier a unit's lines are tagged with the executable's basename,
        # so every Python service on the host logs as "python3" and the
        # `journalctl -t` in the runbook selects three applications at once.
        assert entry(units[name], "Service", "SyslogIdentifier") == name.removesuffix(".service")
        assert entry(units[name], "Service", "StandardOutput") == "journal"
        assert entry(units[name], "Service", "StandardError") == "journal"


# ---------------------------------------------------------------------------
# The units run as the service account, in a sandbox
# ---------------------------------------------------------------------------

class TestTheUnitsAreConfined:
    @pytest.mark.parametrize("name", SANDBOXED_UNITS)
    def test_a_unit_runs_as_the_service_account(self, name, units):
        assert entry(units[name], "Service", "User") == "gstbot"
        assert entry(units[name], "Service", "Group") == "gstbot"

    @pytest.mark.parametrize("name", SANDBOXED_UNITS)
    @pytest.mark.parametrize("directive", sorted(HARDENING))
    def test_a_unit_sets_a_hardening_directive(self, name, directive, units):
        assert entry(units[name], "Service", directive) == HARDENING[directive]

    @pytest.mark.parametrize("name", PYTHON_UNITS)
    def test_a_python_unit_can_still_open_the_sockets_it_needs(self, name, units):
        # RestrictAddressFamilies is the one hardening directive that is easy
        # to get wrong in the direction of breaking the app rather than
        # loosening it: without AF_UNIX, Python's own resolver and any
        # loopback socket activation fail in ways that read as a DNS problem.
        families = entry(units[name], "Service", "RestrictAddressFamilies").split()
        assert set(families) == {"AF_INET", "AF_INET6", "AF_UNIX"}

    def test_the_web_unit_needs_no_unix_sockets(self, units):
        # Narrower than the Python units on purpose, and safe because of one
        # detail: node skips the resolver entirely when listen() is given an
        # IP literal, which the unit's --host is. Widen this the day that
        # ExecStart names a hostname instead, or the bind fails with
        # EAFNOSUPPORT and reads as a DNS outage.
        families = entry(units["gstbot-web.service"], "Service", "RestrictAddressFamilies").split()
        assert set(families) == {"AF_INET", "AF_INET6"}

        command = entry(units["gstbot-web.service"], "Service", "ExecStart")
        host = matched(r"--host (\S+)", command).group(1)
        assert re.fullmatch(r"[\d.]+", host), f"--host {host} needs a resolver, so AF_UNIX too"

    @pytest.mark.parametrize("name", PYTHON_UNITS)
    def test_a_python_unit_gets_a_writable_state_directory(self, name, units):
        # The single writable path under ProtectSystem=strict. Without it the
        # API's startup probe finds UPLOAD_DIR unwritable and every upload 500s.
        assert entry(units[name], "Service", "StateDirectory") == "gstbot"

    def test_the_web_unit_asks_for_no_writable_path(self, units):
        # It only ever reads, and what it reads is under /opt, which
        # ProtectSystem=strict leaves readable. A StateDirectory here would be
        # a writable directory owned by a process that has no reason to write.
        assert not entries(units["gstbot-web.service"], "Service", "StateDirectory")

    @pytest.mark.parametrize("name", PYTHON_UNITS)
    def test_a_python_unit_reads_the_one_environment_file(self, name, units):
        assert entry(units[name], "Service", "EnvironmentFile") == "/etc/gstbot/gstbot.env"

    def test_the_web_unit_is_given_no_secrets(self, units):
        # /etc/gstbot/gstbot.env holds the JWT signing key, the database
        # password and the OpenRouter key. A static file server has no use for
        # any of them, and reading them into its environment would put all
        # three in `/proc/<pid>/environ` for a process reachable from every
        # container on the bridge.
        assert not entries(units["gstbot-web.service"], "Service", "EnvironmentFile")

    @pytest.mark.parametrize("name", PYTHON_UNITS)
    def test_a_python_unit_does_not_write_bytecode(self, name, units):
        # /opt is read-only to these processes. Left unset, every import
        # attempts a .pyc write that fails, which is noise at best.
        assert "PYTHONDONTWRITEBYTECODE=1" in entries(units[name], "Service", "Environment")


# ---------------------------------------------------------------------------
# Ordering: the schema is migrated once, before anything queries it
# ---------------------------------------------------------------------------

class TestTheStackStartsInOrder:
    def test_migrations_are_a_one_shot_that_stays_active(self):
        unit = parse_unit((SYSTEMD / "gstbot-migrate.service").read_text())
        assert entry(unit, "Service", "Type") == "oneshot"
        # Without RemainAfterExit the unit deactivates the moment alembic
        # returns, and the API's Requires= on it would restart it on every
        # API restart — a second `alembic upgrade` racing a running stack.
        assert entry(unit, "Service", "RemainAfterExit") == "yes"
        # A failed migration must stop the release, not retry into a loop.
        assert entry(unit, "Service", "Restart") == "no"

    @pytest.mark.parametrize("name", ["gstbot-api.service", "gstbot-worker.service"])
    def test_a_unit_that_queries_the_schema_waits_for_the_migration(self, name, units):
        assert entry(units[name], "Unit", "Requires") == "gstbot-migrate.service"
        assert "gstbot-migrate.service" in entry(units[name], "Unit", "After")

    def test_the_web_unit_does_not_wait_for_the_migration(self, units):
        # It serves a directory of files and never opens the database, so
        # coupling it to the migration would take the whole SPA — including
        # the page that renders the API's own error — down with a failed
        # `alembic upgrade`.
        assert not entries(units["gstbot-web.service"], "Unit", "Requires")

    @pytest.mark.parametrize("name", SERVING_UNITS)
    def test_a_serving_unit_restarts_but_not_forever(self, name, units):
        assert entry(units[name], "Service", "Restart") == "always"
        assert int(entry(units[name], "Unit", "StartLimitBurst")) > 0

    @pytest.mark.parametrize("name", SERVING_UNITS)
    @pytest.mark.parametrize("directive", ["StartLimitIntervalSec", "StartLimitBurst"])
    def test_the_restart_limit_is_in_the_section_systemd_reads_it_from(
        self, name, directive, units
    ):
        # These moved from [Service] to [Unit] in systemd v229. Left in
        # [Service] they are not an error — systemd logs "Unknown key name"
        # and carries on, so the unit starts, reports active, and rate-limits
        # restarts on the 10s default instead of the 300s written down. An
        # earlier version of this file asserted the value and passed the whole
        # time it was inert, which is why the section is asserted and not just
        # the number.
        assert entries(units[name], "Unit", directive), f"{directive} is not in [Unit]"
        assert not entries(units[name], "Service", directive), (
            f"{directive} in [Service] is ignored by systemd"
        )

    @pytest.mark.parametrize("name", ["gstbot-api.service", "gstbot-web.service"])
    def test_a_unit_that_binds_the_bridge_waits_for_docker(self, name, units):
        # 172.18.0.1 does not exist until dockerd has created the knol_knol
        # bridge. Wants=/After= rather than Requires=: the bridge is a
        # dependency of the address, not of the application, and Restart=always
        # reaches the same place with less coupling if the bind does fail.
        assert "docker.service" in entry(units[name], "Unit", "After")
        assert "docker.service" in entry(units[name], "Unit", "Wants")
        assert "docker.service" not in " ".join(entries(units[name], "Unit", "Requires"))

    def test_only_the_migration_unit_runs_alembic(self, units):
        # The container entrypoint refuses to migrate from the worker for the
        # same reason. Two `alembic upgrade` processes against one database is
        # how a schema ends up half-applied.
        running_alembic = [
            name
            for name, unit in units.items()
            if any("alembic" in v for v in entries(unit, "Service", "ExecStart"))
        ]
        assert running_alembic == ["gstbot-migrate.service"]


# ---------------------------------------------------------------------------
# The commands in ExecStart address code that exists
# ---------------------------------------------------------------------------

class TestTheUnitsRunThisApplication:
    def test_the_api_serves_the_asgi_app_this_repo_defines(self, units):
        command = entry(units["gstbot-api.service"], "Service", "ExecStart")
        assert "app.main:app" in command

        module, _, attribute = "app.main:app".partition(":")
        imported = __import__(module, fromlist=[attribute])
        assert hasattr(imported, attribute)

    def test_the_worker_runs_the_celery_app_this_repo_defines(self, units):
        command = entry(units["gstbot-worker.service"], "Service", "ExecStart")
        assert "-A app.celery_app" in command

        from app.celery_app import celery_app

        assert celery_app.main == "gstbot"

    def test_the_scheduler_has_a_schedule_to_run(self, units):
        # The other half of the unit's existence. An idle beat process reports
        # healthy while doing nothing, which is a worse signal than no process
        # at all — so if the schedule is ever emptied, this unit goes with it.
        command = entry(units["gstbot-beat.service"], "Service", "ExecStart")
        assert "-A app.celery_app beat" in command

        from app.celery_app import celery_app

        assert celery_app.conf.beat_schedule, (
            "gstbot-beat.service ships with nothing to run"
        )

    def test_the_scheduler_publishes_tasks_the_worker_will_have_registered(self):
        # Beat publishes a name. A worker that does not have that name
        # registered rejects the message as unknown, and the schedule silently
        # never runs — no failure on either side, just nothing happening.
        #
        # What makes the worker have it is ``include=``: both processes run
        # `celery -A app.celery_app`, so the modules named there are the ones
        # the worker imports at startup. Importing them here is what that
        # startup does, and the registry is checked after.
        from app.celery_app import celery_app

        for module in celery_app.conf.include:
            __import__(module)

        for name in {e["task"] for e in celery_app.conf.beat_schedule.values()}:
            assert name in celery_app.tasks, f"{name} is scheduled but not registered"

    def test_the_scheduler_writes_its_state_where_it_is_allowed_to(self, units):
        # Both of these are defaults that beat writes relative to the working
        # directory, which is under the read-only /opt. Unset, the unit does
        # not degrade — it fails to start with an error about a shelve file.
        command = entry(units["gstbot-beat.service"], "Service", "ExecStart")

        schedule = matched(r"--schedule=(\S+)", command).group(1)
        assert schedule == BEAT_SCHEDULE_FILE
        state = entry(units["gstbot-beat.service"], "Service", "StateDirectory")
        assert schedule.startswith(f"/var/lib/{state}/")

        assert "--pidfile=" in command
        assert not matched(r"--pidfile=(\S*)", command).group(1), (
            "a pidfile path would be written into the read-only checkout"
        )

    def test_only_one_unit_schedules_anything(self, units):
        # Two beat processes means two of every scheduled run. systemd
        # guarantees one instance of one unit; it cannot help if a second unit
        # also runs `celery beat`, and nothing else would notice.
        scheduling = [
            name
            for name, unit in units.items()
            if any("beat" in v for v in entries(unit, "Service", "ExecStart"))
        ]
        assert scheduling == ["gstbot-beat.service"]

    def test_the_scheduler_does_not_wait_for_the_migration(self, units):
        # It opens no database connection — it publishes a task name and a
        # timestamp to Redis. The worker that runs the task is ordered behind
        # the migration, so a sweep published mid-release queues rather than
        # meeting a half-applied schema.
        assert not entries(units["gstbot-beat.service"], "Unit", "Requires")

    def test_the_web_unit_runs_the_server_this_repo_ships(self, units):
        # The whole reason this unit exists is a file in deploy/. A rename
        # there is otherwise silent until the release restarts it.
        command = entry(units["gstbot-web.service"], "Service", "ExecStart")
        script = matched(rf"{re.escape(INSTALL_ROOT)}/(\S+\.mjs)", command).group(1)
        assert (REPO_ROOT / script).is_file(), f"{script} is not in the repository"
        assert (REPO_ROOT / script) == STATIC_SERVER

    @pytest.mark.parametrize("name", PYTHON_UNITS)
    def test_a_python_unit_runs_from_the_deployed_checkout(self, name, units):
        assert entry(units[name], "Service", "WorkingDirectory") == f"{INSTALL_ROOT}/backend"

    @pytest.mark.parametrize("name", PYTHON_UNITS)
    def test_a_python_unit_uses_an_absolute_path_into_the_deployed_virtualenv(self, name, units):
        command = entry(units[name], "Service", "ExecStart")
        assert command.startswith(f"{INSTALL_ROOT}/.venv/bin/"), command

    def test_the_web_unit_uses_an_absolute_path_to_the_interpreter(self, units):
        # No virtualenv to be in: the server imports nothing but node builtins
        # on purpose, so the production box needs no npm install to serve the
        # SPA. What it does need is an absolute path — systemd runs with no
        # PATH inherited from a login shell, and a bare `node` would resolve
        # against systemd's own default.
        command = entry(units["gstbot-web.service"], "Service", "ExecStart")
        assert command.startswith("/usr/bin/node "), command

    def test_the_static_server_imports_nothing_that_needs_installing(self):
        # The claim above, asserted. An added dependency turns a release into
        # `npm ci` in deploy/ as well, which nothing in deploy.sh does.
        for module in re.findall(r'^import .*? from "([^"]+)";', STATIC_SERVER.read_text(), re.M):
            assert module.startswith("node:"), f"{module} is not a node builtin"

    @pytest.mark.parametrize("name", ["gstbot-api.service", "gstbot-web.service"])
    def test_a_listener_binds_the_bridge_and_not_the_world(self, name, units):
        # The single most consequential line in these files.
        #
        # 127.0.0.1 would be unreachable: Caddy terminates TLS from inside a
        # container, where loopback is the container itself. 0.0.0.0 would
        # publish the service unencrypted on the Hetzner public address
        # alongside the TLS one, and make every rate limit keyed on a
        # forwarded header forgeable by connecting to it directly. The bridge
        # gateway is reachable from the edge and not routed from the internet.
        command = entry(units[name], "Service", "ExecStart")
        assert f"--host {BRIDGE}" in command
        assert "0.0.0.0" not in command
        assert "--host 127.0.0.1" not in command

    def test_the_api_honours_forwarded_headers_only_from_the_edge(self, units):
        # TRUST_PROXY_HEADERS=true is only safe because of this: uvicorn
        # rewrites the client address from X-Forwarded-For for peers on this
        # list and nobody else.
        command = entry(units["gstbot-api.service"], "Service", "ExecStart")
        assert "--proxy-headers" in command

        allowed = matched(r"--forwarded-allow-ips=(\S+)", command).group(1).split(",")
        # One host, not a range and not a wildcard. This bridge carries every
        # other product on the box; widening it to the subnet would let any
        # container forge the client address the rate limiter buckets on.
        assert allowed == [EDGE], allowed
        assert "/" not in command.split("--forwarded-allow-ips=")[1].split()[0]

    def test_the_web_unit_serves_the_directory_the_release_builds(self, units):
        command = entry(units["gstbot-web.service"], "Service", "ExecStart")
        root = matched(r"--root (\S+)", command).group(1)

        assert root == f"{INSTALL_ROOT}/frontend/dist"
        # And that is the path the release script swaps a proven build into
        # before it restarts anything.
        script = DEPLOY_SCRIPT.read_text()
        assert 'FRONTEND="$ROOT/frontend"' in script
        assert 'mv "$FRONTEND/dist.next" "$FRONTEND/dist"' in script

    @pytest.mark.parametrize(
        ("name", "variable"),
        [
            ("gstbot-api.service", "WEB_CONCURRENCY"),
            ("gstbot-worker.service", "CELERY_CONCURRENCY"),
        ],
    )
    def test_a_tunable_has_a_default_in_the_unit(self, name, variable, units):
        # systemd expands ${VAR} to the empty string when it is unset, which
        # would hand uvicorn a bare `--workers` and fail the start. The unit
        # sets a default; the EnvironmentFile is read afterwards and wins.
        keys = [k for k, _ in units[name]["Service"]]
        defaults = " ".join(entries(units[name], "Service", "Environment"))

        assert f"{variable}=" in defaults, f"{variable} has no Environment= default"
        assert keys.index("Environment") < keys.index("EnvironmentFile"), (
            "EnvironmentFile must come after Environment= or it cannot override it"
        )

    def test_every_expanded_variable_has_a_default(self, units):
        # The general form of the check above. systemd does not fail on an
        # unset ${VAR}; it substitutes nothing, so `--loglevel=` reaches the
        # process and celery exits on an argument error five seconds into a
        # release.
        for name in SERVICE_UNITS:
            command = entry(units[name], "Service", "ExecStart")
            defaults = " ".join(entries(units[name], "Service", "Environment"))
            for variable in re.findall(r"\$\{(\w+)\}", command):
                assert f"{variable}=" in defaults, f"{name}: ${{{variable}}} has no default"


# ---------------------------------------------------------------------------
# The production template
# ---------------------------------------------------------------------------

class TestTheEnvironmentTemplate:
    def test_it_refuses_to_boot_as_shipped(self, env_example):
        # A template that started is a template somebody would have left
        # alone. This one fails the production JWT length check.
        with pytest.raises(ValidationError) as caught:
            settings_from(env_example)
        assert "JWT_SECRET" in str(caught.value)

    def test_every_placeholder_is_obvious(self, env_example):
        placeholders = {k for k, v in env_example.items() if "REPLACE_ME" in v}
        # Exactly these three. A fourth would mean a secret was added without
        # a line in the README's setup step; a missing one would mean a real
        # value had been committed.
        assert placeholders == {"JWT_SECRET", "DATABASE_URL", "OPENROUTER_API_KEY"}

    def test_it_boots_clean_once_the_secret_is_filled_in(self, env_example):
        settings = settings_from(env_example, JWT_SECRET=secrets.token_urlsafe(64))

        assert settings.is_production
        # The whole point of the template: nothing to warn about at boot. A
        # deployment that warns on startup is one where somebody has stopped
        # reading the warnings.
        assert validate_startup_config(settings) == []

    def test_it_serves_no_schema_and_no_debug(self, env_example):
        settings = settings_from(env_example, JWT_SECRET=secrets.token_urlsafe(64))

        assert settings.debug is False
        assert settings.docs_enabled is False
        assert settings.log_format == "json"

    def test_its_only_cors_origin_is_the_site_the_edge_serves(self, env_example, site_conf):
        settings = settings_from(env_example, JWT_SECRET=secrets.token_urlsafe(64))

        assert settings.cors_origins == [f"https://{SITE}"]
        assert matched(rf"^{re.escape(SITE)} \{{", site_conf, flags=re.M), (
            "the site block does not define a site for the CORS origin"
        )

    def test_uploads_land_in_the_one_writable_directory(self, env_example, units):
        settings = settings_from(env_example, JWT_SECRET=secrets.token_urlsafe(64))
        declared = entry(units["gstbot-api.service"], "Service", "StateDirectory")
        state_directory = f"/var/lib/{declared}"

        # Anywhere else and ProtectSystem=strict makes the first upload fail.
        assert settings.upload_dir.startswith(state_directory + "/"), settings.upload_dir

    def test_every_backing_service_is_reached_over_the_loopback(self, env_example):
        settings = settings_from(env_example, JWT_SECRET=secrets.token_urlsafe(64))

        for url in (
            settings.database_url,
            settings.redis_url,
            settings.celery_broker_url,
            settings.celery_result_backend,
        ):
            assert "127.0.0.1" in url, f"{url} is not on the loopback"

    def test_the_three_redis_databases_are_distinct(self, env_example):
        settings = settings_from(env_example, JWT_SECRET=secrets.token_urlsafe(64))
        used = [
            redis_db(settings.redis_url),
            redis_db(settings.celery_broker_url),
            redis_db(settings.celery_result_backend),
        ]

        # Not a style point. The cache holds rate-limit counters, the broker
        # holds Kombu's queues and the result backend holds task results; on
        # one database a rate-limit key expiring and a queue key are the same
        # keyspace, and the cache's own flush would eat queued extractions.
        assert len(set(used)) == 3, f"two of {used} are the same Redis database"

    def test_no_redis_database_belongs_to_another_product(self, env_example):
        settings = settings_from(env_example, JWT_SECRET=secrets.token_urlsafe(64))
        used = {
            redis_db(settings.redis_url),
            redis_db(settings.celery_broker_url),
            redis_db(settings.celery_result_backend),
        }

        # This Redis is shared with three other products and has no access
        # control between numbered databases, so a collision is not a
        # permission error — it is two applications' keys interleaving, and a
        # FLUSHDB from either side taking both out. The owners are recorded in
        # the env template beside this setting.
        collisions = used & FOREIGN_REDIS_DBS
        assert not collisions, f"Redis {sorted(collisions)} is already another product's"

    def test_the_connection_ceiling_leaves_room_for_the_shared_cluster(self, env_example):
        settings = settings_from(env_example, JWT_SECRET=secrets.token_urlsafe(64))
        api_workers = int(env_example["WEB_CONCURRENCY"])
        celery_workers = int(env_example["CELERY_CONCURRENCY"])
        per_process = settings.db_pool_size + settings.db_max_overflow
        ours = (api_workers + celery_workers) * per_process

        # Postgres ships with max_connections=100 and reserves 3 for
        # superusers. Exceeding it does not degrade — it refuses connections,
        # which is an outage. And this cluster is shared, so the budget is not
        # ours alone: two thirds is the most GSTIndia may claim of a stock
        # configuration before somebody raises max_connections deliberately.
        assert ours <= 65, f"GSTIndia alone would hold {ours} of ~97 connections"


# ---------------------------------------------------------------------------
# The edge
# ---------------------------------------------------------------------------

class TestTheSiteBlock:
    def test_it_is_a_site_block_and_not_a_whole_caddyfile(self, site_conf):
        # It gets appended to /opt/knol/Caddyfile, which already has a global
        # options block at the top. A second one — or any global directive at
        # the file's left margin — makes the whole shared file invalid, which
        # takes down every site on the box and not only this one.
        assert matched(rf"\A(?:#[^\n]*\n|\s*\n)*{re.escape(SITE)} \{{", site_conf) is not None
        top_level = re.findall(r"^(\S.*?)\s*\{", site_conf, flags=re.M)
        assert top_level == [SITE], f"unexpected top-level block(s): {top_level}"

    def test_it_proxies_the_api_to_the_port_the_unit_listens_on(self, api_block, units):
        upstream = matched(r"reverse_proxy\s+(\S+)", api_block).group(1)

        command = entry(units["gstbot-api.service"], "Service", "ExecStart")
        port = matched(r"--port (\d+)", command).group(1)
        assert upstream == f"{BRIDGE}:{port}"

    def test_it_proxies_everything_else_to_the_spa_server(self, spa_block, units):
        upstream = matched(r"reverse_proxy\s+(\S+)", spa_block).group(1)

        command = entry(units["gstbot-web.service"], "Service", "ExecStart")
        port = matched(r"--port (\d+)", command).group(1)
        assert upstream == f"{BRIDGE}:{port}"

    def test_the_two_upstreams_are_not_the_same_port(self, units):
        ports = {
            name: matched(
                r"--port (\d+)", entry(units[name], "Service", "ExecStart")
            ).group(1)
            for name in ("gstbot-api.service", "gstbot-web.service")
        }
        assert len(set(ports.values())) == 2, ports

    def test_it_claims_no_port_another_product_owns(self, units):
        # 8000 is authmatic-agent's on this box. A unit that took it would
        # start or not depending on boot order, which is the worst version of
        # this failure: it works until a reboot.
        taken = {8000}
        for name in ("gstbot-api.service", "gstbot-web.service"):
            port = int(matched(
                r"--port (\d+)", entry(units[name], "Service", "ExecStart")
            ).group(1))
            assert port not in taken, f"{name} binds {port}, which is already allocated"

    def test_only_the_api_prefix_reaches_the_application(self, site_conf):
        # Everything else is the SPA. A broader matcher would put the static
        # files behind the Python process for no reason.
        assert matched(r"@api path /api/\*", site_conf)

    def test_it_accepts_a_body_larger_than_the_application_will(self, site_conf, env_example):
        edge_mb = int(matched(r"max_size (\d+)MB", site_conf).group(1))
        app_mb = int(env_example["MAX_UPLOAD_MB"])

        # The limit a user meets should be the application's, which answers
        # with a JSON error the UI can render. The edge's exists to stop a
        # multi-gigabyte body reaching Python at all, and if it were the
        # lower of the two every oversized upload would be an opaque 413.
        assert edge_mb > app_mb, f"edge accepts {edge_mb}MB, app accepts {app_mb}MB"

    def test_it_sends_hsts(self, site_conf, env_example):
        max_age = int(matched(r'Strict-Transport-Security "max-age=(\d+)', site_conf).group(1))
        assert max_age >= 31536000
        # The application sends the same header; Caddy replaces rather than
        # appends, so this only agrees rather than duplicates.
        assert env_example["HSTS_ENABLED"] == "true"

    def test_it_does_not_touch_the_api_response_headers(self, api_block):
        # The API's own CSP is `default-src 'none'`, which is stricter than
        # anything appropriate for a page. A site-wide header block would
        # overwrite it with the SPA's and quietly loosen every API response.
        assert "Content-Security-Policy" not in api_block
        assert not re.search(r"^\s*header \{", api_block, flags=re.M)

    def test_the_spa_policy_allows_no_script_it_did_not_ship(self, spa_block):
        policy = matched(r'Content-Security-Policy "([^"]+)"', spa_block).group(1)
        directives = dict(
            (part.split(None, 1) + [""])[:2]
            for part in (p.strip() for p in policy.split(";"))
            if part
        )

        assert directives["default-src"] == "'self'"
        # Exactly these origins. Each is there for one named reason — Umami,
        # and Razorpay Checkout's script — and anything else is a widening
        # somebody should have to justify here. The one hash is the inline
        # service-worker registration index.html carried until a863c71, kept
        # so stale copies of the page can run it and pick up the
        # self-removing sw.js; never 'unsafe-inline'.
        assert directives["script-src"] == (
            "'self' https://analytics.doaide.com https://checkout.razorpay.com"
            " 'sha256-P3upB5nSJgaMZ66JypQ23kO70VzvIaT2MSedNexWFNk='"
        )
        assert "'unsafe-inline'" not in directives["script-src"]
        assert "'unsafe-inline'" not in directives["script-src"]
        assert "'unsafe-eval'" not in policy
        # Same-origin plus the named services only. A script that did get onto
        # the page still cannot post a tenant's invoices to a host of its own.
        assert directives["connect-src"] == (
            "'self' https://analytics.doaide.com https://api.razorpay.com "
            "https://lumberjack.razorpay.com"
        )
        assert directives["frame-src"] == "https://api.razorpay.com https://checkout.razorpay.com"
        assert directives["frame-ancestors"] == "'none'"
        assert directives["object-src"] == "'none'"
        assert directives["base-uri"] == "'none'"

    def test_the_spa_policy_admits_the_inline_styles_the_build_emits(self, spa_block):
        # Several components compute a width through the style attribute (the
        # meters, the dashboard bars). Dropping 'unsafe-inline' from style-src
        # does not fail a test or a build — it silently flattens those to zero
        # in the browser, so the reason it is there is recorded here.
        policy = matched(r'Content-Security-Policy "([^"]+)"', spa_block).group(1)
        style = matched(r"style-src ([^;]+)", policy).group(1)
        assert "'unsafe-inline'" in style

        frontend = REPO_ROOT / "frontend" / "src"
        inline = [
            path.relative_to(REPO_ROOT)
            for path in frontend.rglob("*.jsx")
            if ".test." not in path.name and "style={{" in path.read_text()
        ]
        assert inline, (
            "no component sets an inline style any more — drop 'unsafe-inline' "
            "from style-src in deploy/caddy-gstbot.conf"
        )

    def test_it_passes_the_client_address_the_rate_limiter_reads(self, api_block):
        assert "header_up X-Real-IP {remote_host}" in api_block

    def test_it_waits_long_enough_for_an_inline_parse(self, api_block):
        read_timeout = matched(r"read_timeout (\d+)s", api_block)
        # An upload whose parse falls back to inline processing waits on a
        # free-tier model call; the app allows 90s for it.
        assert int(read_timeout.group(1)) >= 180

    def test_it_health_checks_the_probe_that_touches_nothing(self, api_block):
        # /ready opens the database. Behind a single upstream, a readiness
        # based check only converts the app's own "database is down" JSON into
        # a bare 502 from the edge, which is strictly less information.
        assert "health_uri /api/v1/health/live" in api_block
        assert "/health/ready" not in api_block

    @pytest.mark.skipif(
        subprocess.run(["which", "caddy"], capture_output=True).returncode != 0,
        reason="caddy is not installed; CI validates the file in the deploy job",
    )
    def test_caddy_itself_accepts_the_file(self):
        result = subprocess.run(
            ["caddy", "validate", "--adapter", "caddyfile", "--config", str(SITE_CONF)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


class TestTheComposeEdgeAgreesToo:
    """The nginx in front of the compose stack has the same job as Caddy."""

    def test_nginx_accepts_a_body_larger_than_the_application_will(self):
        nginx = (REPO_ROOT / "frontend" / "nginx.conf").read_text()
        edge_mb = int(matched(r"client_max_body_size (\d+)m", nginx).group(1))

        compose = (REPO_ROOT / "docker-compose.yml").read_text()
        app_mb = int(matched(r"MAX_UPLOAD_MB: \$\{MAX_UPLOAD_MB:-(\d+)\}", compose).group(1))

        assert edge_mb > app_mb, f"nginx accepts {edge_mb}MB, app accepts {app_mb}MB"


# ---------------------------------------------------------------------------
# The release script
# ---------------------------------------------------------------------------

class TestTheDeployScript:
    @pytest.fixture(scope="class")
    def script(self) -> str:
        return DEPLOY_SCRIPT.read_text()

    @pytest.fixture(scope="class")
    def commands(self, script) -> str:
        """The script with its comments stripped and its continuations joined.

        Several assertions below are about what the script *runs*. The
        comments quote the commands they explain, so searching the whole file
        would pass on a line that only exists in prose.

        Continuations are joined because bash joins them: a command wrapped
        over two lines to stay readable is one command, and a search that
        stopped at the newline would report the tail of it as missing.
        """
        kept = "\n".join(
            line for line in script.splitlines() if not line.lstrip().startswith("#")
        )
        return re.sub(r"\\\n\s*", "", kept)

    def test_it_is_executable(self):
        assert DEPLOY_SCRIPT.stat().st_mode & stat.S_IXUSR, "chmod +x deploy/deploy.sh"

    def test_it_is_valid_bash(self):
        result = subprocess.run(
            ["bash", "-n", str(DEPLOY_SCRIPT)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    def test_it_stops_at_the_first_failure(self, script):
        # Without this a failed build carries on to the restart and publishes
        # whatever happened to be in dist/.
        assert "set -euo pipefail" in script

    def test_it_targets_the_directory_the_units_run_from(self, commands, units):
        assert f"ROOT={INSTALL_ROOT}" in commands
        # And that is the parent of every unit's WorkingDirectory.
        for name in PYTHON_UNITS:
            assert entry(units[name], "Service", "WorkingDirectory").startswith(INSTALL_ROOT)

    def test_it_builds_before_it_migrates(self, commands):
        # Order, not presence. The frontend build is the step most likely to
        # fail and the only one with no side effect on the database; running
        # it first means a broken build costs nothing but the operator's time.
        assert commands.index("npm ci") < commands.index("systemctl restart gstbot-migrate")

    def test_it_migrates_before_it_restarts_anything(self, commands):
        # A migration that fails after the restart leaves new code talking to
        # an old schema.
        assert "SERVICES=(gstbot-api.service" in commands
        assert commands.index("systemctl restart gstbot-migrate.service") < commands.index(
            'systemctl restart "${SERVICES[@]}"'
        )

    def test_it_takes_a_restore_point_before_it_migrates(self, commands):
        # Deploying the previous revision undoes the code. It does not undo a
        # dropped column, and the migration is the only step of a release with
        # that property — so the dump belongs immediately before it rather
        # than at 02:30, twelve hours after the change it would undo.
        assert commands.index("gstbot-backup.service") < commands.index(
            "systemctl restart gstbot-migrate.service"
        )

    def test_the_restore_point_is_the_same_dump_the_timer_takes(self, commands):
        # Through the unit, not by calling backup.sh. The unit carries the
        # service account, the sandbox and the EnvironmentFile; a direct call
        # from a root-run release would share none of those and could succeed
        # in a way the nightly one does not — which is the copy that matters.
        assert "systemctl start gstbot-backup.service" in commands
        assert "backup.sh" not in commands

    def test_it_builds_before_it_takes_the_restore_point(self, commands):
        # The build is the step most likely to fail, and a dump taken for a
        # release that then does not happen is pure IO on a shared disk.
        assert commands.index("npm ci") < commands.index("gstbot-backup.service")

    def test_a_failed_backup_stops_the_release(self, commands):
        # The reason to take it is that the next step is unrecoverable. A dump
        # that failed and was carried past is worse than no dump: the release
        # reports a restore point it does not have.
        backup = matched(r"systemctl start gstbot-backup\.service[^\n]*\n?[^\n]*", commands)
        assert "die" in backup.group(0)

    def test_skipping_the_backup_is_possible_and_loud(self, script):
        # The disk being full is a real reason to deploy without a dump, and a
        # release path with no way past a failing backup is one somebody edits
        # under pressure. It warns, because every other use of it is a
        # migration applied with no way back.
        assert "GSTBOT_SKIP_BACKUP" in script
        assert matched(
            r"warn [^\n]*GSTBOT_SKIP_BACKUP|GSTBOT_SKIP_BACKUP[^\n]*\n[^\n]*warn ", script
        )

    def test_it_restarts_the_migration_rather_than_starting_it(self, commands):
        # gstbot-migrate is RemainAfterExit=yes, so it is already "active"
        # from the last release and `systemctl start` is a silent no-op — the
        # release would report success having run no migration at all.
        assert "systemctl restart gstbot-migrate.service" in commands
        assert not re.search(r"systemctl start gstbot-migrate", commands)

    def test_it_restarts_every_serving_unit(self, commands):
        # Naming them rather than restarting the target, because the target
        # would also restart gstbot-migrate a second time. A unit left out
        # here keeps serving the previous release's code.
        # The release restarts the list it also clears the start counter for.
        assert 'systemctl restart "${SERVICES[@]}"' in commands
        restarts = matched(r"SERVICES=\((gstbot-api[^)]*)\)", commands).group(1)
        for name in SERVING_UNITS:
            assert name in restarts, f"{name} is not restarted by a release"

    def test_it_proves_the_build_produced_something_before_restarting(self, commands):
        # `npm run build` can exit 0 having written nothing useful, and the
        # web unit would then restart onto an empty directory and 404 the
        # whole site. Cheaper to notice here.
        assert commands.index("index.html") < commands.index("systemctl restart")

    def test_it_installs_the_backend_from_the_lock(self, commands):
        # The mirror of `npm ci` for Python. requirements.txt is floors, so
        # installing from it resolves whatever PyPI published that morning and
        # the release is not the thing CI ran. --require-hashes is what makes
        # the pin an assertion rather than a preference.
        assert "requirements.lock" in commands
        assert "--require-hashes" in commands
        assert not re.search(r"-r \S*requirements\.txt", commands), (
            "a release must not resolve the floors; that is what the lock is for"
        )

    def test_it_installs_the_frontend_from_the_lockfile(self, commands):
        # `npm install` would resolve versions that were never tested. The
        # comment above that line in the script says so and names it, so the
        # search has to be over what actually runs.
        assert "npm ci" in commands
        assert not re.search(r"npm install\b", commands)

    def test_it_caps_the_build_heap(self, commands):
        # The box is 4 GB and shared. Node sizes its default heap from total
        # RAM, so an uncapped build gets OOM-killed at the rollup stage — and
        # an OOM kill during `npm run build` reports as a bare signal, not as
        # anything naming memory.
        assert "--max-old-space-size" in commands

    def test_it_verifies_the_release_before_reporting_success(self, commands, units):
        # All three: the API on the bridge, the SPA on the bridge, and the
        # site through Caddy. The last is the only one that proves the edge
        # was reloaded with this site block in it.
        api_port = matched(
            r"--port (\d+)", entry(units["gstbot-api.service"], "Service", "ExecStart")
        ).group(1)
        web_port = matched(
            r"--port (\d+)", entry(units["gstbot-web.service"], "Service", "ExecStart")
        ).group(1)

        assert f"http://{BRIDGE}:{api_port}/api/v1/health/ready" in commands
        assert f"http://{BRIDGE}:{web_port}/" in commands
        assert f"https://{SITE}/api/v1/health/live" in commands

    # -- Surviving its own checkout -----------------------------------------
    #
    # The checkout rewrites deploy/deploy.sh, which is the file bash is running
    # from, and bash reads a script lazily by byte offset rather than into
    # memory. Rewritten underneath, the interpreter resumes at the offset it
    # had reached — now pointing into different content — and runs whatever
    # text sits there. Observed: the release that shipped the retrying health
    # checks ran the previous revision's single-shot ones off a file already
    # replaced on disk. Reproduced below with a shorter successor, where the
    # offset lands past the end and the release exits silently mid-run,
    # reporting success.

    @pytest.fixture(scope="class")
    def pin_block(self, script) -> str:
        """The part of the script that re-runs it from a copy git cannot touch.

        Extracted and run for real below rather than pattern-matched. What is
        being asserted is which *content* ends up executing, and reading the
        source is exactly how to get that wrong.
        """
        return matched(
            r'if \[ -z "\$\{GSTBOT_DEPLOY_PINNED:-\}" \]; then\n.*?\nfi\n'
            r"trap [^\n]*\n",
            script,
            flags=re.DOTALL,
        ).group(0)

    def run_release(
        self,
        tmp_path: Path,
        *,
        pin: str = "",
        replaced: bool = True,
        successor: str = 'echo REPLACEMENT "$@"\n',
    ) -> subprocess.CompletedProcess:
        """Run a stand-in release that rewrites itself where the checkout does.

        `cp` stands in for `git checkout`: the same effect on this file,
        without needing a remote. It copies from a file prepared here rather
        than writing a heredoc, because a heredoc would be read back out of the
        descriptor the copy has just truncated — which is the hazard itself.

        Every stage prints, so a failure says how far the release got rather
        than only that it failed.
        """
        release = tmp_path / "deploy.sh"
        nxt = tmp_path / "next.sh"
        nxt.write_text(successor)
        release.write_text(
            "set -euo pipefail\n"
            'die() { echo "$*" >&2; exit 1; }\n'
            f"{pin}"
            'echo START "$@"\n'
            # The path in the checkout, not `$0`: git rewrites the file in
            # $ROOT, which is what bash is reading only when nothing pinned a
            # copy first. Using `$0` would have the pinned run overwrite its
            # own copy and test the opposite of the thing.
            + (f'cp "{nxt}" "{release}"\n' if replaced else "")
            + 'echo MIDDLE "$@"\n'
            'echo END "$@"\n'
        )
        env = {k: v for k, v in os.environ.items() if k != "GSTBOT_DEPLOY_PINNED"}
        return subprocess.run(
            ["bash", str(release), "v1.2.0"],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp_path,
        )

    def test_a_script_rewritten_mid_release_does_not_run_to_the_end(self, tmp_path):
        # The hazard, with no pinning: bash resumes at a byte offset into the
        # replacement, which here is shorter than the offset, so the release
        # stops where it stood. Exit 0 and a partial release — the shape that
        # makes this worth a copy rather than a check.
        result = self.run_release(tmp_path, pin="")
        assert result.stdout.split() == ["START", "v1.2.0"], result.stdout
        assert result.returncode == 0, "and it reported success"

    def test_a_pinned_release_runs_to_the_end_through_its_own_rewrite(
        self, pin_block, tmp_path
    ):
        # The fix. git rewrites the path in $ROOT, this process reads the copy,
        # and the two never meet — so every stage after the checkout runs, and
        # runs from the revision the operator invoked.
        result = self.run_release(tmp_path, pin=pin_block)
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == [
            "START", "v1.2.0", "MIDDLE", "v1.2.0", "END", "v1.2.0",
        ], result.stdout

    def test_the_copy_carries_the_ref_it_was_asked_for(self, pin_block, tmp_path):
        # `exec bash "$pinned"` alone would restart the release as a
        # no-argument one, quietly turning `deploy.sh v1.2.0` into origin/main.
        result = self.run_release(tmp_path, pin=pin_block, replaced=False)
        assert result.stdout.split() == [
            "START", "v1.2.0", "MIDDLE", "v1.2.0", "END", "v1.2.0",
        ], result.stdout

    def test_the_copy_cannot_re_copy_itself_forever(self, pin_block, tmp_path):
        # The exec is guarded by the variable it exports. Unguarded it would
        # fork a release per copy, each restarting services and migrating.
        result = self.run_release(tmp_path, pin=pin_block, replaced=False)
        assert result.stdout.split().count("START") == 1, result.stdout

    def test_the_copy_is_cleaned_up(self, pin_block, tmp_path):
        # It lands in a world-writable directory and holds the release
        # procedure. Left behind, every deploy adds one.
        self.run_release(tmp_path, pin=pin_block, replaced=False)
        assert not list(Path(tempfile.gettempdir()).glob("gstbot-deploy.*")), (
            "the pinned copy outlived the release"
        )

    def test_it_pins_before_it_reaches_the_checkout(self, commands):
        # A copy taken after the rewrite is a copy of the wrong file, and one
        # taken after any side effect leaves the earlier half of the release
        # having run from the descriptor this exists to stop reading.
        assert commands.index("exec bash") < commands.index(
            "checkout --detach origin/main"
        )

    def test_it_says_when_the_release_changed_the_release_procedure(self, commands):
        # This run finishes under the script the operator invoked, which is
        # correct and is not what someone who has just edited deploy.sh
        # expects. Unsaid, it becomes "I fixed the deploy and it did the old
        # thing anyway".
        assert "cmp -s" in commands
        assert matched(r"cmp -s[^\n]*\n(?:[^\n]*\n){0,3}?[^\n]*warn ", commands)

    def test_no_health_check_is_a_single_shot(self, commands):
        # Every check here runs immediately after a restart, so every one of
        # them is asking a question whose answer is "not yet" for a while. A
        # check with no retry does not report whether the release worked, it
        # reports whether the release worked *by the time curl ran*.
        for line in commands.splitlines():
            if "curl" in line and "http" in line:
                assert "$url" in line or "seq" in line, (
                    f"a health check with no retry loop is a race: {line.strip()}"
                )

    def test_the_edge_check_outwaits_caddys_own_health_check(
        self, commands, site_conf
    ):
        # The one check that goes through the edge, and the edge does not learn
        # the API is back at the same moment the API does. Caddy actively
        # probes the upstream on an interval; a probe landing during the
        # uvicorn restart marks it down and holds that verdict until the next
        # one. The API answers on the bridge in about four seconds, so a
        # release that gave up before one full interval had passed failed a
        # deployment that had already succeeded.
        interval = int(
            matched(r"health_interval (\d+)s", site_conf).group(1)
        )
        window = int(
            matched(
                r"await \"the site is answering through Caddy\" \\?\s*\n?\s*"
                r"https://\S+ (\d+)",
                commands,
            ).group(1)
        )
        assert window > interval, (
            f"the edge check gives up after {window}s but Caddy can hold a "
            f"stale down verdict for {interval}s"
        )

    def test_every_health_check_can_fail_the_release(self, commands):
        # `curl` without -f exits 0 on a 500, so a check written that way
        # reports a healthy release for a stack that is answering with
        # nothing but errors.
        for line in commands.splitlines():
            if "curl" in line:
                assert "-fsS" in line, f"curl without -f cannot fail: {line.strip()}"
                assert "--max-time" in line, f"curl without a timeout can hang: {line.strip()}"

    # -- Reaching the remote at all -----------------------------------------
    #
    # These four are about one bug, which cost twelve commits of stale
    # production. The script exports GIT_SSH_COMMAND to force BatchMode so a
    # release from cron cannot hang on a password prompt. But GIT_SSH_COMMAND
    # *replaces* core.sshCommand rather than merging with it, and the checkout
    # on the box pins its read-only deploy key there — so the export threw the
    # key away, every fetch answered "Permission denied (publickey)", the
    # failure went to /dev/null, and the release quietly took the "no
    # reachable remote" branch and re-shipped the tree already on disk. It
    # reported success every time.

    @pytest.fixture(scope="class")
    def ssh_command_block(self, script) -> str:
        """The part of the script that decides what ssh it will fetch with.

        Extracted and run for real below rather than pattern-matched: the
        thing that went wrong was precedence between a config value and an
        environment variable, which reading the source is exactly how to get
        wrong twice.
        """
        return matched(
            r'if \[ -z "\$\{GIT_SSH_COMMAND:-\}" \]; then\n.*?\nfi\n',
            script,
            flags=re.DOTALL,
        ).group(0)

    def derive(self, block: str, root: Path, *, inherited: str | None = None) -> str:
        """Run the block against ``root`` and report the GIT_SSH_COMMAND it set."""
        env = {k: v for k, v in os.environ.items() if k != "GIT_SSH_COMMAND"}
        if inherited is not None:
            env["GIT_SSH_COMMAND"] = inherited
        program = (
            "set -euo pipefail\n"
            f"ROOT={root}\n"
            'have_checkout() { command -v git >/dev/null && [ -d "$ROOT/.git" ]; }\n'
            f"{block}\n"
            'printf %s "${GIT_SSH_COMMAND:-}"\n'
        )
        result = subprocess.run(
            ["bash", "-c", program], capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    @pytest.fixture
    def checkout(self, tmp_path) -> Path:
        subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
        return tmp_path

    def test_forcing_batch_mode_keeps_the_pinned_deploy_key(
        self, ssh_command_block, checkout
    ):
        # The regression itself. The box has no other credential for a private
        # remote, so dropping this identity is the difference between
        # releasing origin/main and releasing whatever is already there.
        key = "/opt/GSTBot/keys/gstbot_deploy_ed25519"
        subprocess.run(
            ["git", "-C", str(checkout), "config", "core.sshCommand", f"ssh -i {key}"],
            check=True,
        )
        derived = self.derive(ssh_command_block, checkout)
        assert key in derived, "the pinned deploy key was thrown away"
        assert "BatchMode=yes" in derived, "a release could still hang on a prompt"

    def test_batch_mode_is_forced_when_nothing_is_pinned(
        self, ssh_command_block, checkout
    ):
        # A checkout with no core.sshCommand is the ordinary case elsewhere,
        # and the hang this protects against is the reason the export exists.
        derived = self.derive(ssh_command_block, checkout)
        assert derived.split() == ["ssh", "-o", "BatchMode=yes"]

    def test_it_works_where_there_is_no_checkout_to_ask(
        self, ssh_command_block, tmp_path
    ):
        # `git config` against a non-repository exits non-zero, and under
        # `set -e` an unguarded read of it would abort the release before any
        # of its own diagnostics had run.
        derived = self.derive(ssh_command_block, tmp_path)
        assert "BatchMode=yes" in derived

    def test_an_ssh_command_from_the_caller_is_left_alone(
        self, ssh_command_block, checkout
    ):
        # An operator overriding it from the environment is deliberate, and
        # the runbook's recovery step for a broken key is exactly that.
        derived = self.derive(ssh_command_block, checkout, inherited="ssh -i /tmp/other")
        assert derived == "ssh -i /tmp/other"

    def test_a_fetch_that_cannot_authenticate_says_so(self, commands):
        # The other half of the bug: the failure was discarded, so a box whose
        # credential had broken looked exactly like a box that never had one —
        # and the second is a supported configuration that releases the local
        # tree on purpose. Falling back is fine; falling back in silence is
        # how it went unnoticed across five releases.
        assert not re.search(r"git -C \"\$ROOT\" fetch[^\n]*2>/dev/null", commands), (
            "a fetch failure discarded here is a stale release reported as a good one"
        )
        fetch = matched(r"fetch_origin\(\) \{.*?\n\}", commands, flags=re.DOTALL).group(0)
        assert "warn " in fetch, "a fetch that failed must reach the operator"


# ---------------------------------------------------------------------------
# The nightly dump
# ---------------------------------------------------------------------------

class TestTheBackupJob:
    """The script, the unit that runs it and the timer that starts it.

    Nothing here proves a dump restores — that needs a database and is a drill,
    not a unit test. What it proves is the set of things that make a backup job
    quietly useless: dumping the wrong database, writing somewhere the sandbox
    forbids, keeping a file nobody checked was readable, or a timer that names
    a unit which does not exist.
    """

    @pytest.fixture(scope="class")
    def script(self) -> str:
        return BACKUP_SCRIPT.read_text()

    @pytest.fixture(scope="class")
    def commands(self, script) -> str:
        """The script without its comments — see TestTheDeployScript."""
        return "\n".join(
            line for line in script.splitlines() if not line.lstrip().startswith("#")
        )

    @pytest.fixture(scope="class")
    def unit(self) -> dict:
        return parse_unit((SYSTEMD / BACKUP_SERVICE).read_text())

    @pytest.fixture(scope="class")
    def timer(self) -> dict:
        return parse_unit((SYSTEMD / BACKUP_TIMER).read_text())

    def test_the_script_is_executable(self):
        assert BACKUP_SCRIPT.stat().st_mode & stat.S_IXUSR, "chmod +x deploy/backup.sh"

    def test_the_script_is_valid_bash(self):
        result = subprocess.run(
            ["bash", "-n", str(BACKUP_SCRIPT)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    def test_it_stops_at_the_first_failure(self, script):
        # Without it, a failed pg_dump carries on to the rename and publishes
        # a truncated file under the name of a good backup.
        assert "set -euo pipefail" in script

    def test_it_dumps_one_database_and_not_the_cluster(self, commands):
        # Postgres here is shared with Herald and HomeNex. `pg_dumpall` would
        # write their tables into a file owned by GSTIndia's service account,
        # which is a data-sharing incident dressed as a backup.
        assert "pg_dumpall" not in commands
        assert "pg_dump " in commands

    def test_it_writes_a_format_that_can_be_restored_selectively(self, commands):
        # Plain SQL restores all-or-nothing. During an incident the thing
        # actually wanted is usually one table as it was last night.
        dump = matched(r"^pg_dump .*", commands, flags=re.M).group(0)
        assert "--format=custom" in dump

    def test_the_password_never_reaches_a_command_line(self, commands):
        # `ps` on this box is readable by four products. libpq takes the
        # password from the environment, so there is no reason for it to be in
        # argv — and DATABASE_URL carries it.
        dump = matched(r"^pg_dump .*", commands, flags=re.M).group(0)
        assert "DATABASE_URL" not in dump
        assert "PGPASSWORD" in commands, "the password has to reach libpq somehow"

    def test_it_reads_the_database_url_the_application_uses(self, commands, unit):
        # Not a second copy of the connection details in the unit or the
        # script. A backup of the database the app used to point at is the
        # failure that is only discovered on the day of a restore.
        assert entry(unit, "Service", "EnvironmentFile") == "/etc/gstbot/gstbot.env"
        assert "/etc/gstbot/gstbot.env" in commands

    def test_it_proves_the_dump_is_readable_before_keeping_it(self, commands):
        # pg_dump exits 0 on a dump truncated by a full disk. Reading the TOC
        # back is what separates having backups from believing you do.
        assert "pg_restore --list" in commands
        assert commands.index("pg_restore --list") < commands.index("mv ")

    def test_a_half_written_dump_is_not_named_like_a_finished_one(self, commands):
        # The retention sweep deletes by glob. If an interrupted run left a
        # *.dump behind, the sweep would treat it as a backup and age out a
        # good one in its place.
        assert ".partial" in commands
        assert matched(r'trap .*rm -f "\$partial"', commands)

    def test_it_keeps_more_than_one_night(self, commands):
        # A single rotating dump is one bad night away from being a copy of
        # the damage rather than of the data.
        days = matched(r'RETENTION_DAYS="?\$\{GSTBOT_BACKUP_RETENTION_DAYS:-(\d+)\}', commands)
        assert int(days.group(1)) >= 7

    def test_the_script_and_the_sandbox_agree_on_where_dumps_go(self, commands, unit):
        # ProtectSystem=strict makes the filesystem read-only, so a directory
        # the script writes to and the unit does not name is an EROFS at 02:30
        # — and the only sign of it is a unit that failed while nobody looked.
        default = matched(r'DEST="?\$\{GSTBOT_BACKUP_DIR:-([^}]+)\}', commands).group(1)
        assert default == BACKUP_DIR
        assert entry(unit, "Service", "ReadWritePaths") == BACKUP_DIR

    def test_the_dumps_do_not_share_a_directory_with_the_originals(self, unit):
        # /var/lib/gstbot is the StateDirectory the application units get, and
        # it holds the uploaded invoices. Backups written into it are lost by
        # whatever loses those.
        assert not entries(unit, "Service", "StateDirectory")

    def test_the_dumps_are_not_world_readable(self, unit):
        # They contain every invoice, every GSTIN and the user table.
        assert entry(unit, "Service", "UMask") == "0077"

    def test_a_failed_dump_is_not_retried_into_a_loop(self, unit):
        assert entry(unit, "Service", "Type") == "oneshot"
        assert entry(unit, "Service", "Restart") == "no"
        # And it does not hold "active" afterwards the way gstbot-migrate does:
        # the timer needs the unit to be inactive to start it again tomorrow.
        assert not entries(unit, "Service", "RemainAfterExit")

    def test_the_unit_runs_the_script_that_ships_with_the_release(self, unit):
        assert entry(unit, "Service", "ExecStart") == f"{INSTALL_ROOT}/deploy/backup.sh"

    def test_a_release_does_not_fire_a_backup(self, unit):
        # `systemctl restart gstbot.target` runs several times on a bad
        # afternoon. PartOf= here would make each of those a full pg_dump
        # against a database the release is already migrating.
        assert not entries(unit, "Unit", "PartOf")
        assert not entries(unit, "Install", "WantedBy")

    def test_the_timer_starts_the_backup_unit(self, timer):
        assert entry(timer, "Timer", "Unit") == BACKUP_SERVICE
        assert entry(timer, "Install", "WantedBy") == "timers.target"

    def test_the_timer_runs_at_least_nightly(self, timer):
        # OnCalendar rather than OnUnitActiveSec: the latter drifts by the
        # runtime of the dump and eventually walks into the working day.
        assert matched(r"\d\d:\d\d:\d\d", entry(timer, "Timer", "OnCalendar"))

    def test_a_missed_night_is_caught_up(self, timer):
        # The box reboots for kernel updates. Without Persistent= a dump whose
        # 02:30 fell inside the window is simply never taken, and the gap is
        # invisible until someone lists the directory.
        assert entry(timer, "Timer", "Persistent") == "true"


class TestTheMonitor:
    """The periodic health check, its unit and its timer.

    systemd already restarts what crashes and the readiness probe already
    holds traffic back from an API that cannot reach its database. Neither
    tells anyone. What this unit exists for is the set of failures that are
    silent by construction — a unit past its start limit, a timer never
    enabled, dumps that stopped, a disk filling — and what the checks below
    assert is that it reports them rather than becoming one of them.
    """

    @pytest.fixture(scope="class")
    def script(self) -> str:
        return MONITOR_SCRIPT.read_text()

    @pytest.fixture(scope="class")
    def commands(self, script) -> str:
        """The script without its comments — see TestTheDeployScript."""
        return "\n".join(
            line for line in script.splitlines() if not line.lstrip().startswith("#")
        )

    @pytest.fixture(scope="class")
    def unit(self) -> dict:
        return parse_unit((SYSTEMD / MONITOR_SERVICE).read_text())

    @pytest.fixture(scope="class")
    def timer(self) -> dict:
        return parse_unit((SYSTEMD / MONITOR_TIMER).read_text())

    def test_the_script_is_executable(self):
        assert MONITOR_SCRIPT.stat().st_mode & stat.S_IXUSR, "chmod +x deploy/monitor.sh"

    def test_the_script_is_valid_bash(self):
        result = subprocess.run(
            ["bash", "-n", str(MONITOR_SCRIPT)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    def test_it_checks_every_unit_that_serves(self, commands):
        # A unit left out here is one whose death is invisible. gstbot-migrate
        # is correctly absent: RemainAfterExit=yes means "active" says only
        # that the last release migrated, which is not a fact about now.
        for name in SERVING_UNITS:
            assert name in commands, f"{name} is not checked"
        assert "gstbot-migrate" not in commands

    def test_it_checks_that_something_is_taking_backups(self, commands):
        # The timer, not the service: gstbot-backup.service is inactive
        # between runs, which is correct and says nothing about whether
        # backups happen. An un-enabled timer is the documented way this box
        # ends up with no backups and no sign of it.
        assert BACKUP_TIMER in commands
        assert BACKUP_SERVICE not in commands

    def test_it_checks_that_a_dump_actually_landed(self, commands):
        # An active timer proves a dump was attempted. Only the directory
        # proves one was written, which is the difference between a backup
        # job that is running and a backup job that is working.
        assert BACKUP_DIR in commands
        assert "-name '*.dump'" in commands

    def test_the_freshness_window_survives_a_late_backup(self, commands):
        # The timer carries 15 minutes of jitter and Persistent= catches up
        # after a reboot, so a 24-hour window reports a dump that is merely
        # late. Anything under two nights is an alert nobody will keep reading.
        hours = matched(
            r'MAX_BACKUP_AGE_HOURS="?\$\{GSTBOT_MONITOR_MAX_BACKUP_AGE_HOURS:-(\d+)\}', commands
        )
        assert int(hours.group(1)) >= 48

    def test_it_checks_the_api_and_the_edge_separately(self, commands):
        # Two requests with different blast radii. Only the bridge failing is
        # the app; only the public URL failing is DNS, TLS or a Caddy that
        # belongs to another product — and knowing which without logging in
        # is most of what a check like this is for.
        assert BRIDGE in commands
        assert SITE in commands

    def test_every_check_has_a_timeout(self, commands):
        # A curl with no timeout against a host that drops packets hangs
        # until TimeoutStartSec, and the report never arrives.
        for line in commands.splitlines():
            if "curl" in line:
                assert "--max-time" in line, f"curl without a timeout can hang: {line.strip()}"

    def test_one_failed_check_does_not_hide_the_rest(self, commands):
        # `set -e` plus a check that exits on the first problem reports a dead
        # API and says nothing about the full disk that caused it. Every
        # failure accumulates and the report comes at the end.
        assert "set -euo pipefail" in commands
        assert "problems+=(" in commands

    def test_it_fails_the_unit_when_a_check_fails(self, commands):
        # The webhook is optional; this is not. `systemctl is-failed
        # gstbot-monitor` has to answer "is anything wrong" on a box where
        # nobody configured a notification channel.
        assert commands.rstrip().endswith("exit 1")

    def test_it_says_nothing_and_exits_clean_when_all_is_well(self, commands):
        # A check that reports every run trains people to ignore it.
        assert matched(r'if \[ "\$\{#problems\[@\]\}" -eq 0 \]', commands)
        assert "exit 0" in commands

    def test_the_alert_channel_is_optional(self, commands):
        # Unset, everything still runs and still lands in the journal behind a
        # failed unit. A monitor that only works once someone has wired up a
        # webhook is one that does nothing on the day it is installed.
        assert matched(r'WEBHOOK="\$\{GSTBOT_ALERT_WEBHOOK:-\}"', commands)
        assert matched(r'if \[ -n "\$WEBHOOK" \]', commands)

    def test_the_alert_body_is_built_by_something_that_escapes(self, commands):
        # Problem lines carry unit names, paths and URLs. One quote pasted
        # into hand-written JSON turns the alert into a 400 from the receiving
        # end — a notification channel that breaks exactly when it is used.
        assert "json.dumps" in commands

    def test_the_monitor_writes_nothing(self, unit):
        # No StateDirectory and no ReadWritePaths under ProtectSystem=strict,
        # so the whole filesystem is read-only to it. "The monitor has a bug"
        # should be a smaller problem than any of the things it watches.
        assert not entries(unit, "Service", "ReadWritePaths")
        assert not entries(unit, "Service", "StateDirectory")

    def test_it_can_reach_the_manager_and_the_resolver(self, unit):
        # `systemctl show` goes over the system D-Bus socket and curl's
        # resolver uses it too. Without AF_UNIX every unit reads as
        # unreadable and the report is confidently wrong.
        assert "AF_UNIX" in entry(unit, "Service", "RestrictAddressFamilies")

    def test_a_failed_check_is_not_retried_into_a_loop(self, unit):
        assert entry(unit, "Service", "Type") == "oneshot"
        assert entry(unit, "Service", "Restart") == "no"
        # And it must not hold "active" afterwards, or the timer cannot start
        # it again in fifteen minutes.
        assert not entries(unit, "Service", "RemainAfterExit")

    def test_the_unit_runs_the_script_that_ships_with_the_release(self, unit):
        assert entry(unit, "Service", "ExecStart") == f"{INSTALL_ROOT}/deploy/monitor.sh"

    def test_a_release_does_not_fire_a_health_check(self, unit):
        # PartOf= would run a check against units that are mid-restart, once
        # per `systemctl restart gstbot.target`, and report the outage the
        # release is currently causing.
        assert not entries(unit, "Unit", "PartOf")
        assert not entries(unit, "Install", "WantedBy")

    def test_the_timer_starts_the_monitor(self, timer):
        assert entry(timer, "Timer", "Unit") == MONITOR_SERVICE
        assert entry(timer, "Install", "WantedBy") == "timers.target"

    def test_it_runs_often_enough_to_notice_an_outage(self, timer):
        # An hourly check makes "the site was down for 55 minutes and nothing
        # said so" a normal outcome.
        minutes = matched(r"^\*:0?/(\d+)$", entry(timer, "Timer", "OnCalendar"))
        assert int(minutes.group(1)) <= 15

    def test_a_missed_check_is_not_caught_up(self, timer):
        # The opposite of the backup timer, on purpose: a check that ran while
        # the box was down would report the state of ten minutes ago, and the
        # next scheduled one reports now.
        assert entry(timer, "Timer", "Persistent") == "false"

    # ---- Run, not read --------------------------------------------------
    # The checks above compare text. These run the script against stubs of
    # the three commands that touch the box, so a check nested where it can
    # be skipped is caught by what the script reports rather than by its
    # shape.

    def run_monitor(self, tmp_path: Path, backup_dir: Path, free_mb: int):
        stubs = tmp_path / "bin"
        stubs.mkdir()
        for name, body in {
            "systemctl": "echo active",
            "curl": "exit 0",
            # Answers for any path, as df does for one on a mounted
            # filesystem, and records which one it was asked about.
            "df": (
                f'echo "$2" > {tmp_path}/df-path\n'
                "echo 'Filesystem 1M-blocks Used Available Capacity Mounted'\n"
                f"echo '/dev/sda1 38000 30000 {free_mb} 99% /'"
            ),
        }.items():
            stub = stubs / name
            stub.write_text(f"#!/bin/sh\n{body}\n")
            stub.chmod(0o755)
        env = {
            "PATH": f"{stubs}:/usr/bin:/bin",
            "GSTBOT_BACKUP_DIR": str(backup_dir),
            "GSTBOT_MONITOR_MIN_FREE_MB": "1024",
        }
        return subprocess.run(
            ["bash", str(MONITOR_SCRIPT)], capture_output=True, text=True, env=env
        )

    def test_a_full_disk_is_reported_when_the_backup_directory_is_missing(
        self, tmp_path
    ):
        # The disk check used to live inside the branch for an existing,
        # readable backup directory, so losing the directory also silenced
        # the one alarm that covers every product on the box.
        missing = tmp_path / "backups" / "gstbot"
        result = self.run_monitor(tmp_path, missing, free_mb=200)
        assert result.returncode == 1
        assert f"{missing} does not exist" in result.stderr
        assert "only 200MiB free" in result.stderr
        # Measured on the nearest directory that does exist — the filesystem
        # the dump would have landed on.
        asked = Path((tmp_path / "df-path").read_text().strip())
        assert asked.resolve() == tmp_path.resolve()

    def test_a_full_disk_is_reported_alongside_a_fresh_backup(self, tmp_path):
        backups = tmp_path / "backups"
        backups.mkdir()
        (backups / "gstbot-tonight.dump").write_bytes(b"x")
        result = self.run_monitor(tmp_path, backups, free_mb=200)
        assert result.returncode == 1
        assert "a dump newer than" in result.stdout
        assert f"only 200MiB free on {backups}" in result.stderr

    def test_a_healthy_box_passes_every_check(self, tmp_path):
        backups = tmp_path / "backups"
        backups.mkdir()
        (backups / "gstbot-tonight.dump").write_bytes(b"x")
        result = self.run_monitor(tmp_path, backups, free_mb=5000)
        assert result.returncode == 0, result.stderr
        assert "All checks passed" in result.stdout


class TestTheJobThatValidatesAllOfThis:
    """The CI job that runs the parsers this suite cannot.

    Everything above compares the manifests against each other as text.
    `systemd-analyze verify` and `caddy validate` are the only things that
    parse them the way the server will, and they run in one job — so that
    job quietly checking nothing is a gap this file cannot otherwise see.

    That is not hypothetical. Its stub tree was written for an install root
    of /srv/gstbot and stayed there after the units moved to /opt/GSTBot,
    so every ExecStart= failed to resolve and the job was red for reasons
    unrelated to any unit. The checks below are about the shape that let
    that happen: paths and file lists in the workflow that duplicate what
    the deploy tree already states.
    """

    @pytest.fixture(scope="class")
    def workflow(self) -> str:
        return (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    @pytest.fixture(scope="class")
    def verify_step(self, workflow) -> str:
        """Just the commands of the step that runs `systemd-analyze verify`.

        Scoped rather than searching the whole file, because `alembic` is a
        word other jobs have every reason to use — and a check that cannot
        tell those apart from a hardcoded stub list is one that passes for
        the wrong reason. Comments are dropped for the same reason they are
        in TestTheDeployScript: prose about a binary is not a use of it.
        """
        steps = workflow.split("- name: ")
        step = next(s for s in steps if s.startswith("Units are valid"))
        return "\n".join(
            line for line in step.splitlines() if not line.lstrip().startswith("#")
        )

    def test_it_stages_the_release_where_the_units_expect_it(self, workflow):
        # The units name absolute paths. If the workflow stages the tree
        # somewhere else, ExecStart= resolves to nothing — or worse, the
        # shipped scripts get stubbed over with empty files and verify passes
        # while checking a release that is not the one in the repository.
        assert f"mkdir -p {INSTALL_ROOT}" in workflow
        assert f"cp -R . {INSTALL_ROOT}/" in workflow

    def test_it_does_not_name_the_binaries_it_stubs(self, verify_step):
        # The list is read out of ExecStart= at run time. Spelling the
        # binaries out again here is what went stale last time, and it goes
        # stale silently: a unit whose binary is missing from a hardcoded
        # list is a unit that stops being verified.
        assert "ExecStart=" in verify_step, "the stub list is no longer derived from the units"
        for unit in SYSTEMD.glob("*.service"):
            binary = matched(r"^ExecStart=[-@+!]*(\S+)", unit.read_text(), flags=re.M).group(1)
            name = Path(binary).name
            if binary.startswith(f"{INSTALL_ROOT}/deploy/"):
                continue  # shipped scripts are staged, not stubbed
            assert name not in verify_step, f"{name} is hardcoded in the workflow again"

    def test_every_unit_that_ships_is_verified(self, workflow):
        # A glob rather than a list, for the same reason. Adding a unit must
        # not also require remembering this file.
        assert "deploy/systemd/*.service" in workflow
        assert "deploy/systemd/*.timer" in workflow
        assert f"deploy/systemd/{TARGET.name}" in workflow

    def test_every_shell_script_that_ships_is_shellchecked(self, workflow):
        # `bash -n` above proves they parse. shellcheck is what catches the
        # unquoted expansion — and a script added without a word here is one
        # whose first real run is at 02:30 on the server.
        checked = matched(r"run: shellcheck ([^\n]+)", workflow).group(1).split()
        shipped = sorted(p.name for p in DEPLOY.iterdir() if p.suffix == ".sh")
        assert sorted(Path(c).name for c in checked) == shipped

    def test_the_edge_config_is_validated_by_the_name_it_has(self, workflow):
        # The one that broke a release before: the job passed because it was
        # validating a filename that no longer existed.
        assert SITE_CONF.name in workflow


class TestTheRunbook:
    @pytest.fixture(scope="class")
    def readme(self) -> str:
        return (DEPLOY / "README.md").read_text()

    def test_it_documents_every_unit_it_ships(self, readme):
        # A unit added without a line here is one nobody knows to install.
        # The timer especially: it is the one unit that does nothing at all
        # until `systemctl enable` is run against it by hand.
        for name in (*SANDBOXED_UNITS, *TIMER_UNITS, "gstbot.target"):
            assert name in readme, f"{name} is undocumented"

    def test_it_documents_the_edge_file_by_the_name_it_has(self, readme):
        assert SITE_CONF.name in readme

    def test_it_records_what_is_deliberately_absent(self, readme):
        # Every product this box runs has a list of things it does not do, and
        # each of them reads as an oversight until it is written down. The
        # off-host backup copy is the one that would otherwise be discovered
        # during an incident.
        assert "Off-host copies" in readme

    def test_it_says_where_beats_schedule_file_lives(self, readme):
        # The one piece of state on this box that is not in Postgres and not an
        # uploaded invoice. Somebody debugging "the sweep did not run" needs to
        # know it exists and that deleting it is safe.
        assert BEAT_SCHEDULE_FILE in readme

    def test_it_names_the_shared_dependencies_as_shared(self, readme):
        # The one thing about this box a newcomer cannot infer from the files:
        # Postgres, Redis and the edge belong to four products. Every
        # destructive operation in an incident — FLUSHALL, a Caddyfile edit, a
        # cluster restart — is wider than it looks.
        assert "FLUSHALL" in readme
        assert "/opt/knol/Caddyfile" in readme


class TestTheRepositoryDoesNotLeakSecrets:
    def test_no_filled_in_environment_file_is_committed(self):
        tracked = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()

        # .env.example and gstbot.env.example are templates and are meant to
        # be here; anything else matching is a real environment file.
        leaked = [
            path
            for path in tracked
            if os.path.basename(path).startswith(".env") or path.endswith(".env")
            if not path.endswith(".example")
        ]
        assert leaked == [], f"environment files are committed: {leaked}"

    def test_no_private_key_is_committed(self):
        # The README's rsync step names an SSH key by path. A key that got
        # copied into the tree instead of referenced from outside it would be
        # pushed to the server and to GitHub in the same motion.
        tracked = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split("\0")

        leaked = []
        for path in filter(None, tracked):
            if path.endswith((".pem", ".key", ".p12", ".pfx")) or "id_ed25519" in path:
                leaked.append(path)
                continue
            full = REPO_ROOT / path
            try:
                head = full.read_bytes()[:64]
            except OSError:  # pragma: no cover - a tracked file that is gone
                continue
            if b"-----BEGIN" in head and b"PRIVATE KEY" in head:
                leaked.append(path)

        assert leaked == [], f"private keys are committed: {leaked}"


def test_the_spa_policy_admits_the_payment_script_the_frontend_loads(spa_block):
    """P18 M16: the pricing page and the report button load Razorpay's
    checkout.js from its origin. A policy without it blocks every payment in
    the browser, silently to the server — so the policy is held to the URL the
    frontend actually uses."""
    frontend = REPO_ROOT / "frontend" / "src" / "lib" / "razorpay.js"
    script = matched(r'SCRIPT_SRC = "(https://[^/"]+)', frontend.read_text()).group(1)
    policy = matched(r'Content-Security-Policy "([^"]+)"', spa_block).group(1)
    assert script in matched(r"script-src ([^;]+)", policy).group(1)


class TestOneReleaseAtATime:
    """P19: two concurrent runs both rebuilt frontend/dist, and the loser's
    failed build left index.html with no assets — a blank site while /health
    answered 200. The pinned copy now takes an exclusive lock before any work."""

    SCRIPT = DEPLOY_SCRIPT.read_text()

    def test_the_lock_is_taken_after_pinning_and_before_any_step(self):
        pin = self.SCRIPT.index('exec bash "$pinned"')
        lock = self.SCRIPT.index("flock -n 9")
        first_step = self.SCRIPT.index('log "', pin)
        assert pin < lock < first_step

    @pytest.mark.skipif(shutil.which("flock") is None, reason="flock(1) is Linux-only")
    def test_a_second_run_is_refused_while_the_lock_is_held(self, tmp_path):
        lock = tmp_path / "deploy.lock"
        holder = subprocess.Popen(["flock", str(lock), "sleep", "30"])
        try:
            time.sleep(0.5)
            env = {**os.environ, "GSTBOT_DEPLOY_LOCK": str(lock), "GSTBOT_DEPLOY_PINNED": "x"}
            result = subprocess.run(
                ["bash", str(DEPLOY_SCRIPT)],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            holder.kill()
        assert result.returncode != 0
        assert "another deploy is running" in result.stderr


class TestFrontendSettingsReachTheBuild:
    """P20 M15: VITE_* values are inlined into the bundle by the build, which
    the units' EnvironmentFile never reaches; the template said to set
    VITE_WHATSAPP_NUMBER without saying where, and gstbot.env did nothing."""

    SCRIPT = DEPLOY_SCRIPT.read_text()

    def test_the_build_exports_vite_lines_from_the_env_file_first(self):
        export = self.SCRIPT.index('case "$line" in VITE_')
        build = self.SCRIPT.index("npm run build")
        assert export < build
        assert "done < /etc/gstbot/gstbot.env" in self.SCRIPT[export:build]

    def test_the_export_skips_comments_and_keeps_values_whole(self, tmp_path):
        env_file = tmp_path / "gstbot.env"
        env_file.write_text("A=1\nVITE_X=+91 98\n# VITE_Y=no\nVITE_Z=ok\n")
        loop = (
            'while IFS= read -r line; do case "$line" in VITE_[A-Z0-9_]*=*) '
            'export "$line" ;; esac; done < "$1"; env | grep ^VITE_ | sort'
        )
        out = subprocess.run(
            ["bash", "-c", loop, "_", str(env_file)], capture_output=True, text=True, check=True
        ).stdout
        assert out.splitlines() == ["VITE_X=+91 98", "VITE_Z=ok"]


class TestATimerNobodyEnabledIsSaid:
    """P23 M8: gstbot-monitor.timer was installed but never enabled on the
    production box, so the checks it runs (backups, disk, a unit that gave up)
    had not run since August, and no release said so."""

    SCRIPT = DEPLOY_SCRIPT.read_text()

    def _loop(self):
        start = self.SCRIPT.index("for timer in gstbot-backup.timer")
        return self.SCRIPT[start : self.SCRIPT.index("done", start) + 4]

    def test_it_runs_after_the_health_checks_and_before_the_release_is_called_done(self):
        loop = self.SCRIPT.index("for timer in gstbot-backup.timer")
        assert self.SCRIPT.index('await "the site is answering') < loop
        assert loop < self.SCRIPT.index('log "Deployed $REVISION"')

    def test_a_disabled_timer_is_named_and_an_enabled_one_is_not(self, tmp_path):
        fake = tmp_path / "systemctl"
        # Enabled: the backup timer. Anything else is not.
        fake.write_text('#!/bin/sh\n[ "$3" = gstbot-backup.timer ]\n')
        fake.chmod(0o755)
        script = "warn() { echo \"warning: $*\" >&2; }\n" + self._loop()
        result = subprocess.run(
            ["bash", "-c", script],
            env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0  # a warning, not a failed release
        assert "gstbot-monitor.timer is not enabled" in result.stderr
        assert "systemctl enable --now gstbot-monitor.timer" in result.stderr
        assert "gstbot-backup.timer" not in result.stderr


class TestTheLiveSiteIsNotWhatTheBuildWritesInto:
    """P23 M12: the frontend was built in place, in the dist gstbot-web serves,
    and vite empties its outDir first: every release took the site down for
    the length of the build, and a failed build left it down, because the
    release stopped there with nothing restoring it."""

    SCRIPT = DEPLOY_SCRIPT.read_text()
    FRONTEND = DEPLOY.parent / "frontend"

    def _swap(self):
        start = self.SCRIPT.index('rm -rf "$FRONTEND/dist.prev"')
        return self.SCRIPT[start : self.SCRIPT.index('"$FRONTEND/dist"\n', start) + 17]

    def test_the_build_writes_beside_the_live_site(self):
        assert "GSTBOT_BUILD_DIR=dist.next" in self.SCRIPT
        assert "process.env.GSTBOT_BUILD_DIR" in (self.FRONTEND / "vite.config.js").read_text()
        # The prerender writes its pages into the same directory vite did.
        prerender = (self.FRONTEND / "scripts" / "prerender.mjs").read_text()
        assert "process.env.GSTBOT_BUILD_DIR" in prerender

    def test_the_swap_happens_only_after_the_build_is_proven(self):
        build = self.SCRIPT.index("GSTBOT_BUILD_DIR=dist.next")
        proven = self.SCRIPT.index('[ -f "$FRONTEND/dist.next/index.html" ]')
        swap = self.SCRIPT.index('mv "$FRONTEND/dist.next" "$FRONTEND/dist"')
        published = self.SCRIPT.index("\npublish_frontend\n")
        # The swap is defined with the build and run after the migrations: see
        # TestTheNewFrontendWaitsForTheMigration.
        assert build < proven < published and swap < published
        # A build that fails stops the release with the live site untouched.
        assert "|| die \"the frontend did not build" in self.SCRIPT

    def test_the_swap_keeps_the_previous_build_and_leaves_no_staging(self, tmp_path):
        frontend = tmp_path / "frontend"
        (frontend / "dist").mkdir(parents=True)
        (frontend / "dist" / "index.html").write_text("old")
        (frontend / "dist.prev").mkdir()  # the release before last: replaced
        (frontend / "dist.next").mkdir()
        (frontend / "dist.next" / "index.html").write_text("new")
        result = subprocess.run(
            ["bash", "-ec", f'FRONTEND="{frontend}"\n' + self._swap()],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert (frontend / "dist" / "index.html").read_text() == "new"
        assert (frontend / "dist.prev" / "index.html").read_text() == "old"
        assert not (frontend / "dist.next").exists()

    def test_the_staging_directories_are_not_tracked(self):
        ignored = (DEPLOY.parent / ".gitignore").read_text().split()
        assert "dist.next/" in ignored and "dist.prev/" in ignored


class TestTheVirtualenvIsWhatTheLockSays:
    """P24 M7: pip install -r never removes, so packages dropped from the lock
    stayed installed on production for good: eight of them, python-jose and
    ecdsa among them with published vulnerabilities, none imported, and none
    visible to an audit of the lock."""

    SCRIPT = DEPLOY_SCRIPT.read_text()

    @pytest.fixture()
    def lock_extras(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("lock_extras", DEPLOY / "lock_extras.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_it_names_what_the_lock_does_not_and_nothing_it_does(self, lock_extras):
        lock = (
            "fastapi==0.141.1 \\\\\n    --hash=sha256:abc\n"
            "uvicorn[standard]==0.52.1 \\\\\n    --hash=sha256:def\n"
            "Typing_Extensions==4.16.0 \\\\\n"
            "# via pydantic\n"
        )
        installed = [
            "fastapi", "uvicorn", "typing-extensions",  # locked, any spelling
            "python-jose", "ECDSA", "passlib",  # left over
            "pip", "setuptools", "gstbot-backend",  # never removed
        ]
        assert lock_extras.extras(lock, installed) == ["ecdsa", "passlib", "python-jose"]

    def test_the_real_lock_parses_to_every_pinned_line(self, lock_extras):
        lock = (REPO_ROOT / "backend" / "requirements.lock").read_text()
        pinned = [line for line in lock.splitlines() if "==" in line and not line.startswith(" ")]
        assert len(lock_extras.locked_names(lock)) == len(pinned) > 50

    def test_the_release_removes_them_right_after_installing(self):
        install = self.SCRIPT.index('--require-hashes -r "$LOCKFILE"')
        prune = self.SCRIPT.index('deploy/lock_extras.py" "$LOCKFILE"')
        uninstall = self.SCRIPT.index('pip" uninstall --quiet --yes $stale')
        assert install < prune < uninstall < self.SCRIPT.index('log "Building the frontend"')


class TestTheMonitorReadsWhatTheHealthEndpointsSay:
    """P24 M8: the monitor checked that units were active and that /health/ready
    answered, but both health endpoints answer 200 while degraded. A worker
    that stopped taking tasks, a scheduler whose deadline sweep stopped firing,
    or Redis going away passed every check."""

    SCRIPT = MONITOR_SCRIPT.read_text()

    @pytest.fixture()
    def health(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "monitor_health", DEPLOY / "monitor_health.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    HEALTHY_JOBS = {
        "health": "ok",
        "celery_enabled": True,
        "workers": {"reachable": True, "names": ["celery@box"]},
        "queue": {"name": "celery", "reachable": True, "depth": 0},
        "jobs": [
            {"name": "filing-deadline-sweep", "last_run": "2026-10-29T01:30:00Z", "stale": False}
        ],
    }

    def test_healthy_jobs_report_nothing(self, health):
        assert health.job_problems(self.HEALTHY_JOBS, 100) == []

    @pytest.mark.parametrize(
        ("change", "expected"),
        [
            ({"workers": {"reachable": False}}, "no Celery worker answers"),
            ({"queue": {"reachable": False, "depth": None}}, "task queue cannot be read"),
            ({"queue": {"reachable": True, "depth": 250}}, "250 tasks are waiting"),
            (
                {"jobs": [{"name": "filing-deadline-sweep", "last_run": None, "stale": True}]},
                "filing-deadline-sweep has not run on time (last run never)",
            ),
            ({"health": "degraded"}, "background jobs report 'degraded'"),
        ],
    )
    def test_each_way_jobs_go_wrong_is_named(self, health, change, expected):
        doc = {**self.HEALTHY_JOBS, **change, "health": change.get("health", "degraded")}
        problems = health.job_problems(doc, 100)
        assert any(expected in p for p in problems), problems

    def test_a_worker_is_not_expected_when_celery_is_off(self, health):
        doc = {**self.HEALTHY_JOBS, "celery_enabled": False, "workers": {"reachable": False}}
        assert health.job_problems(doc, 100) == []

    def test_a_core_dependency_down_is_named_and_an_optional_one_is_not(self, health):
        doc = {"status": "ok", "checks": {
            "database": {"status": "ok"},
            "redis": {"status": "unavailable"},
            "storage": {"status": "ok"},
            "ai": {"status": "unconfigured"},
        }}
        assert health.health_problems(doc) == ["redis is unavailable according to /health"]

    def test_a_body_that_is_not_json_is_a_problem_not_a_crash(self, health):
        assert health.main(["x", "jobs"], "<html>502</html>")
        assert health.main(["x", "health"], "")

    def test_the_script_reads_both_endpoints_and_records_what_they_say(self):
        assert "api/v1/health/jobs" in self.SCRIPT and "api/v1/health}" in self.SCRIPT
        assert 'python3 "$HEALTH_HELPER" "$kind" "$MAX_QUEUE_DEPTH"' in self.SCRIPT
        assert '[ -n "$line" ] && fail "$line"' in self.SCRIPT
        # Recorded before the verdict, so a problem here fails the unit and
        # reaches the webhook like any other.
        assert self.SCRIPT.index('fail "$line"') < self.SCRIPT.index('echo "All checks passed"')


class TestRollingTheFrontendBack:
    """P24 M12: the README's rollback was `mv dist dist.bad && mv dist.prev dist`.
    With no dist.prev (a fresh box, or a second rollback) the first move
    succeeded and the second failed, leaving no dist: the rollback was the
    outage. deploy/rollback-frontend.sh checks before it moves anything."""

    SCRIPT = DEPLOY / "rollback-frontend.sh"

    def _run(self, tmp_path, *, lock_free=True):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        fake = bin_dir / "flock"
        fake.write_text(f"#!/bin/sh\nexit {0 if lock_free else 1}\n")
        fake.chmod(0o755)
        return subprocess.run(
            ["bash", str(self.SCRIPT)],
            env={
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "GSTBOT_FRONTEND_DIR": str(tmp_path / "frontend"),
                "GSTBOT_DEPLOY_LOCK": str(tmp_path / "deploy.lock"),
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

    def _builds(self, tmp_path, **builds):
        frontend = tmp_path / "frontend"
        for name, marker in builds.items():
            (frontend / name).mkdir(parents=True)
            (frontend / name / "index.html").write_text(marker)
        return frontend

    def test_with_nothing_to_go_back_to_the_site_is_left_alone(self, tmp_path):
        frontend = self._builds(tmp_path, dist="live")
        result = self._run(tmp_path)
        assert result.returncode != 0
        assert "no previous build" in result.stderr
        assert (frontend / "dist" / "index.html").read_text() == "live"

    def test_it_swaps_and_running_it_again_undoes_it(self, tmp_path):
        frontend = self._builds(tmp_path, dist="new", **{"dist.prev": "old"})
        (frontend / ".dist-source").write_text("tree-vite")
        assert self._run(tmp_path).returncode == 0
        assert (frontend / "dist" / "index.html").read_text() == "old"
        assert (frontend / "dist.prev" / "index.html").read_text() == "new"
        # The record of what dist was built from no longer describes it.
        assert not (frontend / ".dist-source").exists()
        assert self._run(tmp_path).returncode == 0
        assert (frontend / "dist" / "index.html").read_text() == "new"

    def test_it_waits_its_turn_behind_a_deploy(self, tmp_path):
        frontend = self._builds(tmp_path, dist="new", **{"dist.prev": "old"})
        result = self._run(tmp_path, lock_free=False)
        assert result.returncode != 0 and "a deploy is running" in result.stderr
        assert (frontend / "dist" / "index.html").read_text() == "new"

    def test_the_readme_points_at_the_script_not_the_two_moves(self):
        readme = (DEPLOY / "README.md").read_text()
        assert "deploy/rollback-frontend.sh" in readme
        assert "mv dist dist.bad && mv dist.prev dist" not in readme.split("```sh")[-1]


class TestAnUnchangedFrontendIsNotRebuilt:
    """P24 M12: a release whose frontend had not changed rebuilt it anyway,
    npm ci from the registry and the slowest step of the release, to produce
    the same bytes."""

    SCRIPT = DEPLOY_SCRIPT.read_text()

    def _source_fn(self):
        start = self.SCRIPT.index("frontend_source() {")
        return self.SCRIPT[start : self.SCRIPT.index("\n}\n", start) + 3]

    def _source_id(self, root):
        script = (
            f'ROOT="{root}"\n'
            'have_checkout() { command -v git >/dev/null && [ -d "$ROOT/.git" ]; }\n'
            + self._source_fn()
            + "frontend_source\n"
        )
        return subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=20
        ).stdout.strip()

    def test_the_source_id_follows_the_frontend_tree_and_nothing_else(self, tmp_path):
        if shutil.which("git") is None or shutil.which("sha256sum") is None:
            pytest.skip("needs git and sha256sum")
        git = ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        (tmp_path / "frontend").mkdir()
        (tmp_path / "frontend" / "app.js").write_text("one")
        (tmp_path / "backend.py").write_text("x")
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "1"], check=True)
        first = self._source_id(tmp_path)
        assert first

        (tmp_path / "backend.py").write_text("y")  # outside frontend/
        subprocess.run([*git, "commit", "-qam", "2"], check=True)
        assert self._source_id(tmp_path) == first

        (tmp_path / "frontend" / ".dist-source").write_text(first)  # untracked
        assert self._source_id(tmp_path) == first

        (tmp_path / "frontend" / "app.js").write_text("two")  # uncommitted
        assert self._source_id(tmp_path) == ""  # unknown: always build
        subprocess.run([*git, "commit", "-qam", "3"], check=True)
        assert self._source_id(tmp_path) not in ("", first)

    def test_the_build_is_skipped_only_on_a_matching_record_and_a_live_build(self):
        skip = self.SCRIPT.index('if [ -n "$source_id" ] && [ -f "$FRONTEND/dist/index.html" ]')
        record = self.SCRIPT.index(
            '[ "$(cat "$FRONTEND/.dist-source" 2>/dev/null)" = "$source_id" ]'
        )
        build = self.SCRIPT.index("GSTBOT_BUILD_DIR=dist.next")
        written = self.SCRIPT.index('echo "$source_id" > "$FRONTEND/.dist-source"')
        swap = self.SCRIPT.index('mv "$FRONTEND/dist.next" "$FRONTEND/dist"')
        assert skip < record < build
        # The swap and the record it writes live in publish_frontend, which
        # runs after the migrations; the record is still written after the swap.
        assert swap < written
        # Cleared before a build starts, so a failed one cannot leave it vouching.
        assert self.SCRIPT.index('rm -f "$FRONTEND/.dist-source"') < build
        assert ".dist-source" in (REPO_ROOT / ".gitignore").read_text()


class TestAReleaseRestartIsNotACrashLoop:
    """P24 M12: the units allow five starts in 300 s so a crash loop stops, and
    a release's restart counted against that like a crash. The third release
    inside five minutes was refused with start-limit-hit, the API and worker
    stayed down for four minutes, and deploy.sh stopped under set -e with no
    error line at all."""

    SCRIPT = DEPLOY_SCRIPT.read_text()

    def test_the_start_counter_is_cleared_before_the_restart(self):
        reset = self.SCRIPT.index('systemctl reset-failed "${SERVICES[@]}"')
        restart = self.SCRIPT.index('systemctl restart "${SERVICES[@]}"')
        assert reset < restart
        # Every unit the release restarts has its counter cleared: one list.
        assert self.SCRIPT.count("SERVICES=(") == 1

    def test_a_restart_that_fails_says_so(self):
        restart = self.SCRIPT.index('systemctl restart "${SERVICES[@]}"')
        assert self.SCRIPT[restart:].lstrip().split("\n")[1].strip().startswith(
            '|| die "the services did not restart'
        )

    def test_the_limit_it_works_around_is_still_there(self):
        # Clearing the counter is only safe because the limit stays for what
        # it is for: a unit that keeps crashing on its own.
        api = (DEPLOY / "systemd" / "gstbot-api.service").read_text()
        assert "StartLimitBurst=5" in api and "Restart=always" in api


class TestTheBackupReadsAnEncodedPassword:
    """P25 M2: backup.sh split DATABASE_URL with urlsplit, which returns the
    user, password and database still percent-encoded, so a password holding
    "@", "/" or "%" (written p%40ss in the URL) reached pg_dump as the literal
    p%40ss and every dump, nightly and pre-release, failed to authenticate."""

    def _connection(self, url):
        script = BACKUP_SCRIPT.read_text()
        start = script.index("python3 - <<'PY'\n") + len("python3 - <<'PY'\n")
        body = script[start : script.index("\nPY\n", start)]
        result = subprocess.run(
            ["python3", "-c", body],
            env={**os.environ, "DATABASE_URL": url},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        exported = {}
        for line in result.stdout.splitlines():
            name, _, value = line.removeprefix("export ").partition("=")
            exported[name] = shlex.split(value)[0] if value else ""
        return exported

    def test_the_parts_reach_libpq_decoded(self):
        env = self._connection("postgresql+psycopg://gst%2Buser:p%40ss%2Fw0rd@db.local:5433/gst%5Fdb")
        assert env == {
            "PGHOST": "db.local",
            "PGPORT": "5433",
            "PGUSER": "gst+user",
            "PGPASSWORD": "p@ss/w0rd",
            "PGDATABASE": "gst_db",
        }

    def test_a_plain_url_is_unchanged(self):
        env = self._connection("postgresql://gstbot:secret@172.18.0.1/gstbot")
        assert (env["PGUSER"], env["PGPASSWORD"], env["PGPORT"]) == ("gstbot", "secret", "5432")


class TestAReleaseInstallsChangedUnits:
    """P25 M12: no release installed the units after the first, by hand, so a
    unit edit reached main and never the box; every installed service still
    named the old domain. The block now runs on every release."""

    SCRIPT = DEPLOY_SCRIPT.read_text()

    def _block(self) -> str:
        start = self.SCRIPT.index('log "Installing changed systemd units"')
        end = self.SCRIPT.index('log "Taking a restore point"')
        return self.SCRIPT[start:end]

    def test_it_runs_before_the_restore_point_and_the_restart(self):
        installs = self.SCRIPT.index('log "Installing changed systemd units"')
        assert installs < self.SCRIPT.index("systemctl start gstbot-backup.service")
        assert installs < self.SCRIPT.index('systemctl restart "${SERVICES[@]}"')

    def _run(self, tmp_path, repo_units: dict[str, str], installed: dict[str, str]):
        root = tmp_path / "root"
        (root / "deploy" / "systemd").mkdir(parents=True)
        etc = tmp_path / "etc"
        etc.mkdir()
        for name, text in repo_units.items():
            (root / "deploy" / "systemd" / name).write_text(text)
        for name, text in installed.items():
            (etc / name).write_text(text)
        calls = tmp_path / "calls"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "systemctl"
        stub.write_text(f'#!/bin/sh\necho "$*" >> {calls}\n')
        stub.chmod(0o755)
        script = (
            'log() { :; }\n'
            f'ROOT={root}\n'
            + self._block().replace("/etc/systemd/system", str(etc))
        )
        subprocess.run(
            ["bash", "-c", script],
            check=True,
            env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
            capture_output=True,
        )
        return etc, (calls.read_text().splitlines() if calls.exists() else [])

    def test_a_changed_unit_is_installed_and_reloaded(self, tmp_path):
        etc, calls = self._run(
            tmp_path,
            {"a.service": "new\n", "b.service": "same\n", "c.timer": "t2\n"},
            {"a.service": "old\n", "b.service": "same\n", "c.timer": "t1\n"},
        )
        assert (etc / "a.service").read_text() == "new\n"
        assert (etc / "c.timer").read_text() == "t2\n"
        assert "daemon-reload" in calls
        # Enabled-ness is asked, then the timer restarted so it reschedules.
        assert "is-enabled --quiet c.timer" in calls
        assert "restart c.timer" in calls

    def test_an_unchanged_release_touches_nothing(self, tmp_path):
        _, calls = self._run(tmp_path, {"a.service": "x\n"}, {"a.service": "x\n"})
        assert calls == []


class TestARollbackPastAMigrationStillStarts:
    """P25 M12: after any release that added a migration, `deploy.sh
    <previous-sha>` stamped nothing new but ran `alembic upgrade head` from a
    tree that lacks the database's revision. Alembic stops with "Can't locate
    revision", gstbot-migrate fails, and the API and worker that Requires= it
    refuse to start, on the rollback and on every boot after it."""

    CHECK = DEPLOY / "migration_check.py"

    def test_the_migration_unit_asks_first(self):
        unit = parse_unit((SYSTEMD / "gstbot-migrate.service").read_text())
        assert entries(unit, "Service", "ExecCondition") == [
            "/opt/GSTBot/.venv/bin/python /opt/GSTBot/deploy/migration_check.py"
        ]
        assert self.CHECK.is_file()

    def _check(self, url: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.CHECK)],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "DATABASE_URL": url},
            capture_output=True,
            text=True,
        )

    def _migrated(self, tmp_path) -> str:
        url = f"sqlite:///{tmp_path / 'db.sqlite'}"
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "DATABASE_URL": url},
            check=True,
            capture_output=True,
        )
        return url

    def test_a_database_at_this_trees_head_is_migrated(self, tmp_path):
        assert self._check(self._migrated(tmp_path)).returncode == 0

    def test_a_database_ahead_of_this_tree_is_skipped(self, tmp_path):
        import sqlite3

        url = self._migrated(tmp_path)
        with sqlite3.connect(tmp_path / "db.sqlite") as db:
            db.execute("UPDATE alembic_version SET version_num = '0999_from_the_future'")
        result = self._check(url)
        # 1 is "skip" to systemd's ExecCondition; the unit is not failed.
        assert result.returncode == 1
        assert "0999_from_the_future" in result.stderr

    def test_an_unreachable_database_fails_rather_than_skips(self):
        # Skipping here would start the API on an unmigrated schema.
        result = self._check("postgresql+psycopg://nobody@127.0.0.1:1/none")
        assert result.returncode == 255


def test_the_release_is_recorded_before_the_restart_that_loads_it():
    script = DEPLOY_SCRIPT.read_text()
    written = script.index('printf \'%s\\n\' "$REVISION" > "$ROOT/backend/.release"')
    assert written < script.index('systemctl restart "${SERVICES[@]}"')
    assert "backend/.release" in (REPO_ROOT / ".gitignore").read_text().splitlines()


class TestTheNewFrontendWaitsForTheMigration:
    """P29 M14: the new build went live before the release could still fail.

    ``static-server.mjs`` opens each file by path per request, so renaming
    ``dist.next`` to ``dist`` *is* the frontend release — not the restart at
    the end. The swap ran before the restore point and the migrations, so a
    failed backup or migration aborted the release with users already on the
    new UI against the old API, and even a release that went well served that
    mix for the whole migration.
    """

    SCRIPT = DEPLOY_SCRIPT.read_text()

    def _function(self, name):
        start = self.SCRIPT.index(f"{name}() {{")
        return self.SCRIPT[start : self.SCRIPT.index("\n}\n", start) + 3]

    def _from_restore_point_to_health(self):
        start = self.SCRIPT.index('log "Taking a restore point"')
        return self.SCRIPT[start : self.SCRIPT.index('log "Checking health"')]

    def test_the_swap_runs_after_the_migration_and_before_the_restart(self):
        call = self.SCRIPT.index("\npublish_frontend\n")
        assert self.SCRIPT.index("systemctl restart gstbot-migrate.service") < call
        assert call < self.SCRIPT.index('systemctl restart "${SERVICES[@]}"')
        # And the build step itself no longer moves anything into dist.
        build = self.SCRIPT[
            self.SCRIPT.index('log "Building the frontend"') : self.SCRIPT.index(
                'log "Installing changed systemd units"'
            )
        ]
        assert 'mv "$FRONTEND/dist.next" "$FRONTEND/dist"' not in build

    def _run(self, tmp_path, *, migrate_fails):
        frontend = tmp_path / "frontend"
        for name, text in (("dist", "old"), ("dist.next", "new")):
            (frontend / name).mkdir(parents=True)
            (frontend / name / "index.html").write_text(text)
        (tmp_path / "backend").mkdir()
        harness = "\n".join([
            f'FRONTEND="{frontend}"; ROOT="{tmp_path}"; REVISION=abc; source_id=""',
            "frontend_staged=1",
            "log() { :; }; warn() { :; }",
            'die() { echo "died: $*" >&2; exit 1; }',
            # gstbot-migrate fails when asked to; everything else succeeds.
            "systemctl() { case \"$*\" in *gstbot-migrate*) "
            + ("return 1" if migrate_fails else "return 0")
            + ";; *) return 0;; esac; }",
            self._function("publish_frontend"),
            self._from_restore_point_to_health(),
        ])
        return frontend, subprocess.run(
            ["bash", "-c", harness], capture_output=True, text=True, timeout=20
        )

    def test_a_failed_migration_leaves_the_live_site_on_the_old_build(self, tmp_path):
        frontend, result = self._run(tmp_path, migrate_fails=True)
        assert result.returncode != 0 and "migrations failed" in result.stderr
        assert (frontend / "dist" / "index.html").read_text() == "old"
        assert (frontend / "dist.next" / "index.html").read_text() == "new"

    def test_a_good_migration_publishes_the_new_build(self, tmp_path):
        frontend, result = self._run(tmp_path, migrate_fails=False)
        assert result.returncode == 0, result.stderr
        assert (frontend / "dist" / "index.html").read_text() == "new"
        assert (frontend / "dist.prev" / "index.html").read_text() == "old"
        assert not (frontend / "dist.next").exists()


class TestRestorePointsAreThinnedNotJustAged:
    """P30 M7: every release takes a restore point, and retention was age alone.

    backup.sh pruned dumps older than RETENTION_DAYS and nothing else, so the
    count was set by how often anyone deployed: 162 dumps on the box after a
    day of releases, a run of identical ones per hour. Tiny while the database
    is, and a full disk — which fails the backup, which stops every release
    before it migrates — once it is not. Capping the count instead would let a
    burst of releases delete the nightly dumps a late-noticed problem needs.
    """

    SCRIPT = BACKUP_SCRIPT.read_text()

    def _thin(self):
        start = self.SCRIPT.index("thin_dumps() {")
        return self.SCRIPT[start : self.SCRIPT.index("\n}\n", start) + 3]

    def _dump(self, directory, stamp, age_hours):
        import os
        import time

        path = directory / f"gstbot-{stamp}.dump"
        path.write_text(stamp)
        when = time.time() - age_hours * 3600
        os.utime(path, (when, when))
        return path.name

    def test_older_dumps_keep_the_first_and_newest_of_each_day_and_today_keeps_all(self, tmp_path):
        today = [self._dump(tmp_path, f"20261029T1{n}0000Z", 1 + n) for n in range(3)]
        three_days = [
            self._dump(tmp_path, "20261026T024000Z", 80),
            self._dump(tmp_path, "20261026T133700Z", 74),
            self._dump(tmp_path, "20261026T142200Z", 73),
        ]
        five_days = [self._dump(tmp_path, "20261024T024100Z", 122)]

        run = subprocess.run(
            ["bash", "-c", f'set -euo pipefail\nDEST="{tmp_path}"\n' + self._thin() + "thin_dumps"],
            capture_output=True, text=True, timeout=20,
        )

        assert run.returncode == 0, run.stderr
        left = sorted(p.name for p in tmp_path.iterdir())
        # Each older day keeps its first dump and its last; the middle goes.
        assert left == sorted([*today, three_days[0], three_days[-1], *five_days])

    def test_a_day_of_releases_keeps_the_state_from_before_the_first(self, tmp_path):
        """The newest dump of a release day is taken after its migrations ran.

        Keeping only that one deleted the 02:30 nightly and the first release's
        restore point — the only copies of the database as it stood before
        that day's changes. A migration that damaged data, noticed the next
        morning, then had nothing nearer than the previous day to go back to,
        and every real entry made in between was lost with the damage.
        """
        nightly = self._dump(tmp_path, "20261026T023000Z", 40)
        before_release = self._dump(tmp_path, "20261026T100000Z", 32)
        between = self._dump(tmp_path, "20261026T120000Z", 30)
        after_last_release = self._dump(tmp_path, "20261026T150000Z", 27)

        run = subprocess.run(
            ["bash", "-c", f'set -euo pipefail\nDEST="{tmp_path}"\n' + self._thin() + "thin_dumps"],
            capture_output=True, text=True, timeout=20,
        )

        assert run.returncode == 0, run.stderr
        left = sorted(p.name for p in tmp_path.iterdir())
        assert nightly in left and after_last_release in left
        assert before_release not in left and between not in left
        assert f"Thinned {between}" in run.stdout

    def test_a_day_with_two_dumps_keeps_both(self, tmp_path):
        kept = [
            self._dump(tmp_path, "20261025T023000Z", 60),
            self._dump(tmp_path, "20261025T180000Z", 50),
        ]
        run = subprocess.run(
            ["bash", "-c", f'set -euo pipefail\nDEST="{tmp_path}"\n' + self._thin() + "thin_dumps"],
            capture_output=True, text=True, timeout=20,
        )
        assert run.returncode == 0, run.stderr
        assert sorted(p.name for p in tmp_path.iterdir()) == sorted(kept)

    def test_thinning_runs_after_a_verified_dump(self):
        verified = self.SCRIPT.index('mv "$partial" "$target"')
        assert verified < self.SCRIPT.index("\nthin_dumps\n")


class TestTheFrontendIsNotBuiltOnABoxWithNoRoomForIt:
    """P33 M14: the release built the frontend on the server unconditionally.

    The box has 8 GB shared by many products. On 2026-10-29 a release's vite
    build swapped it to a load average of 180, SSH stopped answering for the
    length of it, and the build was killed ("Terminated") with the release
    half-done. The only way round it was a hand-written wrapper that pre-seeded
    .dist-source to fool the script into skipping its own build. A build made
    off the box is now something the script accepts, and one on it is refused
    rather than started when memory is short.
    """

    SCRIPT = DEPLOY_SCRIPT.read_text()

    def _fn(self, name):
        start = self.SCRIPT.index(f"{name}() {{")
        return self.SCRIPT[start : self.SCRIPT.index("\n}\n", start) + 3]

    def _run(self, body, **env):
        prelude = "".join(f'{k}="{v}"\n' for k, v in env.items())
        prelude += "warn() { printf 'warning: %s\\n' \"$*\" >&2; }\n"
        return subprocess.run(
            ["bash", "-c", prelude + body], capture_output=True, text=True, timeout=20
        )

    def _upload(self, frontend, source):
        upload = frontend / "dist.upload"
        upload.mkdir(parents=True)
        (upload / "index.html").write_text("built elsewhere")
        (upload / ".source").write_text(source + "\n")

    def test_an_uploaded_build_of_this_tree_is_staged_like_one_made_here(self, tmp_path):
        frontend = tmp_path / "frontend"
        self._upload(frontend, "tree-vite")

        run = self._run(
            self._fn("stage_uploaded_build") + "stage_uploaded_build\n",
            FRONTEND=frontend, source_id="tree-vite",
        )

        assert run.returncode == 0, run.stderr
        assert (frontend / "dist.next" / "index.html").read_text() == "built elsewhere"
        assert not (frontend / "dist.upload").exists()
        # The marker is the upload's, not the site's: it is not served.
        assert not (frontend / "dist.next" / ".source").exists()

    def test_an_upload_of_some_other_tree_is_discarded_not_published(self, tmp_path):
        frontend = tmp_path / "frontend"
        self._upload(frontend, "old-tree-vite")

        run = self._run(
            self._fn("stage_uploaded_build") + "stage_uploaded_build\n",
            FRONTEND=frontend, source_id="tree-vite",
        )

        assert run.returncode != 0
        assert not (frontend / "dist.next").exists()
        assert not (frontend / "dist.upload").exists()
        assert "old-tree-vite" in run.stderr

    def test_no_upload_means_nothing_staged(self, tmp_path):
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        run = self._run(
            self._fn("stage_uploaded_build") + "stage_uploaded_build\n",
            FRONTEND=frontend, source_id="tree-vite",
        )
        assert run.returncode != 0 and not (frontend / "dist.next").exists()

    @pytest.mark.parametrize(("available_kb", "room"), [(800_000, False), (3_000_000, True)])
    def test_a_build_needs_the_memory_floor_free(self, tmp_path, available_kb, room):
        meminfo = tmp_path / "meminfo"
        meminfo.write_text(f"MemTotal: 8000000 kB\nMemAvailable: {available_kb} kB\n")
        run = self._run(
            self._fn("room_to_build") + "room_to_build\n",
            MEMINFO=meminfo, BUILD_MIN_FREE_MB="1536",
        )
        assert (run.returncode == 0) is room

    def test_the_release_uses_an_upload_first_and_checks_memory_before_npm(self):
        upload = self.SCRIPT.index("elif stage_uploaded_build; then")
        check = self.SCRIPT.index("room_to_build ||")
        npm = self.SCRIPT.index("npm ci --no-audit --no-fund")
        assert upload < check < npm
        refusal = self.SCRIPT[check : check + 400]
        assert "die" in refusal and "dist.upload" in refusal

    def test_the_upload_directory_is_not_tracked(self):
        assert "dist.upload/" in (DEPLOY.parent / ".gitignore").read_text().split()


class TestTheUploadedOriginalsAreBackedUp:
    """P34 M7: the dumps restored every row, and none of the documents.

    backup.sh dumped the database and said, in its own header, that
    /var/lib/gstbot/invoices "is not dumped here. A restore gives back every
    row, including the paths of files that are no longer there." Each invoice
    row points at the uploaded original — the scan an assessment asks for —
    and nothing kept a copy. Now each run takes a snapshot beside the dump:
    rsync against the previous one with --link-dest, so a file that has not
    changed costs a hard link rather than a second copy.
    """

    SCRIPT = BACKUP_SCRIPT.read_text()

    def _fn(self, name):
        start = self.SCRIPT.index(f"{name}() {{")
        return self.SCRIPT[start : self.SCRIPT.index("\n}\n", start) + 3]

    def _run(self, body, **env):
        prelude = "".join(f'{k}="{v}"\n' for k, v in env.items())
        prelude += "log() { printf '%s\\n' \"$*\"; }\n"
        prelude += "die() { printf 'error: %s\\n' \"$*\" >&2; exit 1; }\n"
        return subprocess.run(
            ["bash", "-c", "set -euo pipefail\n" + prelude + body],
            capture_output=True, text=True, timeout=30,
        )

    def _snapshot(self, uploads, dest, stamp):
        return self._run(
            self._fn("snapshot_uploads") + "snapshot_uploads\n",
            UPLOADS=uploads, DEST=dest, stamp=stamp,
        )

    @pytest.fixture()
    def needs_rsync(self):
        if shutil.which("rsync") is None:
            pytest.skip("needs rsync")

    def test_a_snapshot_holds_the_files_and_shares_the_unchanged_ones(self, tmp_path, needs_rsync):
        uploads, dest = tmp_path / "invoices", tmp_path / "backups"
        (uploads / "7").mkdir(parents=True)
        dest.mkdir()
        (uploads / "7" / "kept.pdf").write_text("scan")
        (uploads / "7" / "deleted.pdf").write_text("gone soon")

        first = self._snapshot(uploads, dest, "20261029T023000Z")
        (uploads / "7" / "deleted.pdf").unlink()
        second = self._snapshot(uploads, dest, "20261030T023000Z")

        assert first.returncode == 0 and second.returncode == 0, first.stderr + second.stderr
        old, new = dest / "uploads-20261029T023000Z", dest / "uploads-20261030T023000Z"
        assert (new / "7" / "kept.pdf").read_text() == "scan"
        assert not (new / "7" / "deleted.pdf").exists()
        assert (old / "7" / "deleted.pdf").exists()  # the earlier snapshot still has it
        assert (old / "7" / "kept.pdf").stat().st_ino == (new / "7" / "kept.pdf").stat().st_ino
        assert not list(dest.glob("*.partial"))

    def test_a_box_with_no_upload_directory_is_not_a_failed_backup(self, tmp_path, needs_rsync):
        dest = tmp_path / "backups"
        dest.mkdir()
        run = self._snapshot(tmp_path / "missing", dest, "20261029T023000Z")
        assert run.returncode == 0, run.stderr
        assert list(dest.iterdir()) == []

    def test_older_snapshots_keep_the_first_and_newest_of_each_day(self, tmp_path):
        import os
        import time

        def snap(stamp, age_hours):
            path = tmp_path / f"uploads-{stamp}"
            path.mkdir()
            when = time.time() - age_hours * 3600
            os.utime(path, (when, when))
            return path.name

        today = [snap("20261029T100000Z", 2), snap("20261029T120000Z", 1)]
        day = [snap("20261026T023000Z", 80), snap("20261026T120000Z", 75),
               snap("20261026T150000Z", 72)]

        run = self._run(self._fn("thin_snapshots") + "thin_snapshots\n", DEST=tmp_path)

        assert run.returncode == 0, run.stderr
        left = sorted(p.name for p in tmp_path.iterdir())
        assert left == sorted([*today, day[0], day[-1]])

    def test_it_runs_after_the_verified_dump_and_ages_out_with_it(self):
        verified = self.SCRIPT.index('mv "$partial" "$target"')
        assert verified < self.SCRIPT.index("\nsnapshot_uploads\n")
        assert "-name 'uploads-*' -mtime \"+$RETENTION_DAYS\"" in self.SCRIPT
        assert "\nthin_snapshots\n" in self.SCRIPT
        assert "is not dumped here" not in self.SCRIPT
