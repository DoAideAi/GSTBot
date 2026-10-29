"""The workflow that is supposed to be checking everything else.

Two things go wrong with a CI file, and neither of them shows up as a failing
run — which is the whole problem, because a failing run is the only signal
anyone is watching for.

The first is a check that was never added. ``deploy/`` ships a Caddyfile, four
systemd units and a release script, and none of them is exercised by importing
the application, so none of them was parsed by anything until the ``deploy``
job existed. A missing brace in the Caddyfile is not a test failure; it is
``systemctl reload caddy`` failing partway through a release.

The second is a version that drifted apart. CI installs one Python, the image
builds on the one in its Dockerfile, and the server installs the one the
runbook names. Nothing makes those the same number, and when they stop being
the same number the suite goes on passing against a runtime nobody deploys.

So everything here reads the workflow as data and asserts that what runs is
what some other file in the repository already claims runs.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from app.core.routes import collect_api_routes
from app.main import app

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY = REPO_ROOT / "deploy"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def jobs(workflow) -> dict:
    return workflow["jobs"]


def commands(job: dict) -> str:
    """Every shell command a job runs, as one blob to search.

    Which step a command lives in is not interesting to any assertion below —
    only whether the job runs it at all — and joining them means a step that
    gets split in two does not fail a test that has nothing to do with it.
    """
    return "\n".join(step["run"] for step in job["steps"] if "run" in step)


def triggers(workflow: dict) -> dict:
    """The ``on:`` block.

    PyYAML follows YAML 1.1, where a bare ``on`` is the boolean true rather
    than the string — so this key is ``True`` after a round trip through
    ``safe_load``, and every naive ``workflow["on"]`` raises KeyError. GitHub
    reads it as a string. Both spellings are accepted here so that quoting the
    key in the workflow later does not break this file.
    """
    return workflow.get("on", workflow.get(True))


# ---------------------------------------------------------------------------
# The workflow itself
# ---------------------------------------------------------------------------

class TestTheWorkflowIsWiredUp:
    def test_it_gates_the_branch_that_gets_deployed(self, workflow):
        # main is what reaches the server: deploy.sh releases the tree rsync'd
        # from it, and fetches origin/main when the box can reach the remote.
        # A workflow that only ran on pull requests would leave the branch the
        # server installs from as the one thing nothing checks.
        on = triggers(workflow)
        assert "main" in on["push"]["branches"]
        assert "main" in on["pull_request"]["branches"]

    def test_it_reads_and_writes_nothing(self, workflow):
        # The default token is read/write on everything. None of these jobs
        # push, comment or tag, so the whole workflow runs read-only.
        assert workflow["permissions"] == {"contents": "read"}

    @pytest.mark.parametrize("name", ["backend", "frontend", "docker", "deploy"])
    def test_a_job_exists(self, name, jobs):
        assert name in jobs

    def test_every_job_gives_up_eventually(self, jobs):
        # A step that hangs — a pull that stalls, a test that waits on a socket
        # — runs for six hours on the default timeout, and does it on every
        # push until somebody notices the bill.
        missing = [name for name, job in jobs.items() if "timeout-minutes" not in job]
        assert missing == []


# ---------------------------------------------------------------------------
# The deployment manifests are parsed by the tools that will parse them
# ---------------------------------------------------------------------------

class TestEveryManifestIsRunThroughItsOwnTool:
    """``test_deploy.py`` checks these files against each other and against the
    application. It cannot check them against their own parsers, because none
    of those parsers is installed here. This is the other half."""

    @pytest.fixture(scope="class")
    def deploy_job(self, jobs) -> str:
        return commands(jobs["deploy"])

    def test_the_caddyfile_is_validated_by_caddy(self, deploy_job):
        assert "caddy validate" in deploy_job
        assert "deploy/caddy-gstbot.conf" in deploy_job

    def test_the_caddyfile_is_held_to_caddys_own_formatting(self, deploy_job):
        # Not tidiness. `caddy validate` downgrades a formatting complaint to a
        # warning and repeats it on every reload, so without a check that
        # fails, the file accumulates a permanent warning and the next real one
        # arrives somewhere nobody is looking.
        assert "caddy fmt" in deploy_job

    def test_the_units_are_validated_by_systemd(self, deploy_job):
        # The one check that catches a misspelled hardening directive. systemd
        # ignores an unknown key, so `ProtectSytem=strict` is a unit that
        # starts, reports active, and confines nothing.
        assert "systemd-analyze verify" in deploy_job

    def test_every_shell_script_that_ships_is_shellchecked(self, deploy_job):
        # `bash -n` in test_deploy.py proves these parse. Only shellcheck
        # catches the unquoted expansion and the exit status swallowed by a
        # pipeline — and a script added here and left out of the line below is
        # one whose first real run is on the server.
        shellcheck = next(line for line in deploy_job.splitlines() if "shellcheck" in line)
        for script in sorted(p.name for p in DEPLOY.glob("*.sh")):
            assert f"deploy/{script}" in shellcheck, f"{script} is not shellchecked"

    def test_every_unit_that_ships_is_covered_by_the_verify(self, deploy_job):
        # A glob rather than the four names, so a unit added tomorrow is
        # verified by the line that already exists — or this fails and says so.
        verify = next(
            line for line in deploy_job.splitlines() if "systemd-analyze verify" in line
        )
        for unit in sorted(p.name for p in (DEPLOY / "systemd").iterdir()):
            covered = unit in verify or re.search(
                rf"deploy/systemd/\*{re.escape(Path(unit).suffix)}\b", verify
            )
            assert covered, f"{unit} is not passed to systemd-analyze verify"


class TestTheMigrationsAreCheckedAgainstTheDatabaseTheyDeployAgainst:
    """The suite migrates SQLite; the server migrates Postgres.

    ``tests/test_migrations.py`` runs on a throwaway SQLite file by default and
    switches to whatever ``MIGRATION_TEST_DATABASE_URL`` names. That second run
    is the only place the rollback assertions ever meet a real ``ALTER TABLE``,
    and it lives entirely in the workflow — so it is the kind of check that can
    be dropped in an edit here without a single test going red.
    """

    @pytest.fixture(scope="class")
    def backend_job(self, jobs) -> dict:
        return jobs["backend"]

    def test_the_migration_module_is_re_run_against_postgres(self, backend_job):
        step = self._rerun_step(backend_job)
        assert step is not None, (
            "no step runs tests/test_migrations.py with MIGRATION_TEST_DATABASE_URL; "
            "the rollback checks only ever see SQLite"
        )

    def test_it_points_at_the_postgres_service_the_job_starts(self, backend_job):
        # A URL naming a database nothing started fails the step outright, but
        # one naming the *wrong* reachable database would quietly test somewhere
        # else. The service block is the only Postgres in this job.
        step = self._rerun_step(backend_job)
        assert step is not None
        url = step["env"]["MIGRATION_TEST_DATABASE_URL"]
        service = backend_job["services"]["postgres"]["env"]
        assert service["POSTGRES_DB"] in url
        assert service["POSTGRES_USER"] in url

    def test_it_runs_after_the_steps_that_need_a_migrated_database(self, backend_job):
        """Ordering is load-bearing, and silently so.

        The module's fixture wipes the shared database on the way out. Any step
        ordered after it that expects a schema — `alembic check`, today — finds
        an empty database and fails for a reason with nothing to do with it.
        """
        steps = backend_job["steps"]
        rerun = steps.index(self._rerun_step(backend_job))
        needs_schema = [
            index
            for index, step in enumerate(steps)
            if "run" in step and "alembic check" in step["run"]
        ]

        assert needs_schema, "expected an `alembic check` step to order against"
        assert all(index < rerun for index in needs_schema), (
            "the migration module wipes the database it is given; steps that "
            "need a migrated one have to come before it"
        )

    @staticmethod
    def _rerun_step(job: dict) -> dict | None:
        return next(
            (
                step
                for step in job["steps"]
                if "MIGRATION_TEST_DATABASE_URL" in (step.get("env") or {})
                and "tests/test_migrations.py" in step.get("run", "")
            ),
            None,
        )


# ---------------------------------------------------------------------------
# One runtime version, written down in four places
# ---------------------------------------------------------------------------

def sole(values: set[str], what: str) -> str:
    assert len(values) == 1, f"{what} disagree: {sorted(values)}"
    return values.pop()


class TestTheRuntimeVersionsAgree:
    @pytest.fixture(scope="class")
    def with_python(self, jobs) -> str:
        """The Python the suite is actually run on in CI."""
        step = next(
            s
            for s in jobs["backend"]["steps"]
            if s.get("uses", "").startswith("actions/setup-python")
        )
        return str(step["with"]["python-version"])

    @pytest.fixture(scope="class")
    def with_node(self, jobs) -> str:
        step = next(
            s
            for s in jobs["frontend"]["steps"]
            if s.get("uses", "").startswith("actions/setup-node")
        )
        return str(step["with"]["node-version"])

    def test_the_image_is_built_on_the_python_ci_tests_on(self, with_python):
        dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text()
        stages = set(re.findall(r"^FROM python:(\S+?)-slim", dockerfile, flags=re.M))
        assert stages, "backend/Dockerfile does not build on a python: tag"
        # Both stages too: a build stage on one minor and a runtime stage on
        # another produces wheels the runtime cannot import for any dependency
        # that ships a compiled extension.
        assert sole(stages, "backend/Dockerfile python stages") == with_python

    def test_the_server_installs_the_python_ci_tests_on(self, with_python):
        # The runbook's apt line. A server on 3.11 running a suite that only
        # ever ran on 3.12 is a syntax error found by the first deploy.
        readme = (DEPLOY / "README.md").read_text()
        installed = set(re.findall(r"python(3\.\d+)", readme))
        assert sole(installed, "deploy/README.md python versions") == with_python

    def test_the_declared_floor_is_one_the_suite_has_run_on(self, with_python):
        pyproject = (BACKEND / "pyproject.toml").read_text()
        floor = re.search(r'requires-python = ">=(\d+\.\d+)"', pyproject)
        assert floor is not None
        # `>=3.11` while CI only ever runs 3.12 is a claim nothing backs. It is
        # allowed to be lower — the deployment resolves newer — but not higher.
        assert tuple(map(int, floor.group(1).split("."))) <= tuple(
            map(int, with_python.split("."))
        )

    def test_the_frontend_image_is_built_on_the_node_ci_tests_on(self, with_node):
        dockerfile = (REPO_ROOT / "frontend" / "Dockerfile").read_text()
        majors = set(re.findall(r"^FROM node:(\d+)", dockerfile, flags=re.M))
        assert sole(majors, "frontend/Dockerfile node stages") == with_node

    # P29 M20: CI and the image ran Node 20 while the box that builds every
    # release's frontend (deploy.sh runs `npm ci && npm run build` there) runs
    # 22 — so CI never tested the Node that produces what ships, and nothing
    # said so, because nothing declared a Node at all. And 20 had left
    # maintenance six months earlier.

    # Node majors and the day upstream stopped patching them.
    NODE_END_OF_LIFE = {"16": "2023-09-11", "18": "2025-04-30", "20": "2026-04-30"}

    def test_the_frontend_declares_the_node_ci_tests_on(self, with_node):
        package = json.loads((REPO_ROOT / "frontend" / "package.json").read_text())
        engines = (package.get("engines") or {}).get("node")
        assert engines, "frontend/package.json declares no engines.node"
        assert re.match(r"\^?>?=?\s*(\d+)", engines).group(1) == with_node

    def test_ci_does_not_test_on_a_node_past_end_of_life(self, with_node):
        from datetime import date

        ended = self.NODE_END_OF_LIFE.get(with_node)
        assert ended is None or date.fromisoformat(ended) > date.today(), (
            f"Node {with_node} stopped receiving fixes on {ended}"
        )

    def test_a_release_refuses_to_build_on_another_node(self, tmp_path):
        # The box builds the frontend, so its Node is part of the release.
        # Run the real check against a fake `node` of each major.
        script = (DEPLOY / "deploy.sh").read_text()
        start = script.index("check_node() {")
        check = script[start : script.index("\n}\n", start) + 3]
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        (frontend / "package.json").write_text('{"engines": {"node": ">=22"}}')
        results = {}
        for version in ("v22.23.1", "v20.19.0"):
            fake = tmp_path / version
            fake.mkdir()
            (fake / "node").write_text(f"#!/bin/sh\necho {version}\n")
            (fake / "node").chmod(0o755)
            run = subprocess.run(
                ["bash", "-c", f'FRONTEND="{frontend}"\ndie() {{ echo "$*" >&2; exit 1; }}\n'
                 + check + "check_node"],
                capture_output=True, text=True, timeout=10,
                env={"PATH": f"{fake}:/usr/bin:/bin"},
            )
            results[version] = (run.returncode, run.stderr)
        assert results["v22.23.1"][0] == 0, results
        assert results["v20.19.0"][0] != 0 and "22" in results["v20.19.0"][1]


# ---------------------------------------------------------------------------
# The front door
# ---------------------------------------------------------------------------


class TestTheREADMEDescribesThisRepository:
    """The README is the one file a newcomer reads before anything else.

    Which makes a stale line in it more expensive than a stale line anywhere
    else: a wrong command is met with an error message at the exact moment the
    reader has no way to tell a mistake in the document from a broken
    checkout. And nothing about a README fails — it is not imported, not
    linted, and not run.

    This is the same trade the version tests above make: read the prose as data
    and assert that what it claims is what some other file in the repository
    already says. Only the claims a reader would act on, and only the ones with
    something in the tree to check them against — every assertion here is a
    line someone could have followed and been wrong.
    """

    @pytest.fixture(scope="class")
    def readme(self) -> str:
        return (REPO_ROOT / "README.md").read_text()

    @pytest.fixture(scope="class")
    def prose(self, readme) -> str:
        """*readme* with its line breaks flattened.

        A claim this file asserts on is a sentence, and a sentence in a hard-
        wrapped document is split at whatever column it reached — so a
        substring check against the raw text passes or fails on where the
        wrapping happened to fall, which is not something a reader would
        notice or an author should have to preserve.
        """
        return " ".join(readme.split())

    def test_every_file_it_links_to_is_here(self, readme):
        # Relative markdown links, which is every link in it that is not a URL.
        # A moved runbook is how a reader's first click 404s.
        for target in re.findall(r"\]\((?!https?:)([^)#]+)\)", readme):
            assert (REPO_ROOT / target).exists(), f"README links to missing {target}"

    def test_the_python_it_tells_you_to_build_a_venv_with_is_the_one_ci_runs(
        self, readme, jobs
    ):
        # deploy/README.md is already held to this. The front door was not, and
        # it is the copy someone actually runs on a laptop — a venv on a
        # different minor resolves different wheels and the first failure looks
        # like a broken checkout rather than a wrong number in a document.
        step = next(
            s
            for s in jobs["backend"]["steps"]
            if s.get("uses", "").startswith("actions/setup-python")
        )
        named = set(re.findall(r"python(3\.\d+)", readme))
        assert sole(named, "README.md python versions") == str(step["with"]["python-version"])

    def test_every_npm_script_it_names_exists(self, readme):
        package = json.loads((REPO_ROOT / "frontend" / "package.json").read_text())
        for script in set(re.findall(r"npm (?:run )?([a-z:]+)", readme)):
            if script in {"install", "ci"}:  # npm's own, not ours
                continue
            assert script in package["scripts"], f"README runs missing npm script {script}"

    def test_every_python_module_it_tells_you_to_run_is_importable(self, readme):
        # `-m tools.mutation`, `-A app.celery_app`, `app.main:app`. A module
        # that was renamed leaves a command that fails with an import error,
        # which reads as a broken environment.
        modules = set(re.findall(r"-m (app\.[\w.]+|tools\.[\w.]+)", readme))
        modules |= set(re.findall(r"-A ([\w.]+) (?:worker|beat)", readme))
        modules |= {m.split(":")[0] for m in re.findall(r"\b(app\.\w+:\w+)", readme)}
        assert modules, "the README stopped naming any runnable module"
        for module in modules:
            assert (
                BACKEND / Path(module.replace(".", "/") + ".py")
            ).exists(), f"README runs missing module {module}"

    def test_the_coverage_gates_it_quotes_are_the_gates(self, readme, prose):
        # This is the claim with a history of drifting: the frontend branch
        # threshold was raised and CLAUDE.md went on quoting the old number for
        # long enough that it was the number people believed.
        pyproject = (BACKEND / "pyproject.toml").read_text()
        backend_gate = re.search(r"^fail_under = (\d+)", pyproject, flags=re.M)
        assert backend_gate is not None
        assert f"{backend_gate.group(1)}% backend" in readme

        vite = (REPO_ROOT / "frontend" / "vite.config.js").read_text()
        # `[\d.]+`, not `\d+`. A gate is not always a whole number — branches
        # sits at 99.5 — and the integer pattern matched the "99" off the front
        # of it and stopped. That is the one failure this test cannot afford:
        # it read a raised gate as the old one, agreed with a README quoting
        # the old one, and passed. A drift check that cannot see the drift is
        # worse than no drift check, because it is believed.
        thresholds = dict(
            (name, value)
            for name, value in re.findall(r"(\w+): ([\d.]+)", _thresholds_block(vite))
        )
        assert thresholds, "could not read the frontend thresholds"
        # Statements and lines still share a figure, and are quoted as one. A
        # threshold that leaves the group has to be written out on its own, so
        # each is asserted where it is actually stated.
        shared = {thresholds[name] for name in ("statements", "lines")}
        assert (
            f"statements and lines at {sole(shared, 'frontend statements/lines')}"
            in prose
        )
        assert f"branches at {thresholds['branches']}" in prose

    def test_it_names_the_route_count_the_api_actually_publishes(self, readme, client):
        # The one number in it that no other file states, and the one a reader
        # cannot check for themselves without starting the API.
        claimed = re.search(r"(\d+) routes under `/api/v1`", readme)
        assert claimed is not None, "the README stopped stating a route count"
        # `/openapi.json`, not under the versioned prefix — the spec describes
        # the API rather than being part of it.
        paths = client.get("/openapi.json").json()
        if "paths" not in paths:  # pragma: no cover - the spec route moved
            pytest.fail("could not read the published spec")
        published = sum(
            1
            for operations in paths["paths"].values()
            for method in operations
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        )
        # The README counts the routes that are served, as its per-area table
        # does (test_readme_routes); the spec leaves out the ones mounted with
        # include_in_schema=False — the Razorpay webhook. Counting only the
        # spec made the two tests demand different totals of one sentence.
        hidden = sum(
            len(route.methods - {"HEAD", "OPTIONS"})
            for route in collect_api_routes(app)
            if getattr(route, "methods", None)
            and route.path.startswith("/api/v1/")
            and not getattr(route, "include_in_schema", True)
        )
        assert hidden, "expected the schema-hidden webhook among the served routes"
        assert int(claimed.group(1)) == published + hidden

    def test_it_reads_a_gate_that_is_not_a_whole_number(self):
        # The check above is only worth anything if it can see the gate it is
        # checking. Read with `\d+`, "99.5" matched as "99" — so a raised gate
        # was read as the old one, the README quoting the old one agreed with
        # it, and the drift check passed over exactly the drift it exists to
        # catch. Asserted on a literal block rather than on the real config,
        # because the real one will not always have a decimal in it and this
        # has to keep failing when the pattern narrows again.
        block = _thresholds_block(
            "thresholds: { statements: 99, branches: 99.5, functions: 87, lines: 99 },"
        )
        found = dict(re.findall(r"(\w+): ([\d.]+)", block))
        assert found == {
            "statements": "99",
            "branches": "99.5",
            "functions": "87",
            "lines": "99",
        }


def _thresholds_block(vite: str) -> str:
    match = re.search(r"thresholds: \{([^}]*)\}", vite)
    assert match is not None, "vite.config.js has no coverage thresholds block"
    return match.group(1)
