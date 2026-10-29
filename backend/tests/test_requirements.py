"""The declared dependency floors against what is actually installed.

Every line in requirements.txt is a `>=` floor rather than a pin, so nothing
here checks that a particular version is present — the deployment is free to
resolve newer. What it checks is the other direction: that the floor is a claim
the environment can back up.

That matters because the floors are maintained by Dependabot, which raises them
without ever running the suite against the raised number. A bumped floor is
therefore an assertion nobody verified: the PR says "this project needs at least
alembic 1.18.5" while CI installs whatever pip resolves and the tests pass for
reasons unrelated to the floor. If the two drift — a floor raised above what is
resolvable, or a package dropped from the file but still imported — the failure
surfaces at `pip install` on a clean machine, which is the worst place for it.

Asserting floor <= installed catches the drift here instead, and makes the next
floor bump self-verifying: the suite either runs against a version that honours
the new floor or it goes red.
"""
from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

BACKEND = Path(__file__).resolve().parent.parent
LOCKFILE = BACKEND / "requirements.lock"

# One pinned distribution in the lock: the name, the exact version, and the
# `# via` lines beneath it naming what pulled it in.
_PIN = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==(?P<version>[^ ;\\]+)", re.MULTILINE)


def _requirements(filename: str) -> list[Requirement]:
    """Parse a requirements file, skipping comments, blanks and `-r` includes."""
    lines = (BACKEND / filename).read_text().splitlines()
    return [
        Requirement(stripped)
        for line in lines
        if (stripped := line.strip())
        # `-r requirements.txt` is followed on its own, by the caller passing
        # both filenames; recursing here would double every runtime package.
        if not stripped.startswith(("#", "-"))
    ]


def _lock() -> dict[str, str]:
    """The lock as ``{canonical name: version}``."""
    return {
        canonicalize_name(m.group("name")): m.group("version")
        for m in _PIN.finditer(LOCKFILE.read_text())
    }


def _blocks() -> list[tuple[str, str]]:
    """The lock as ``[(name, everything up to the next pin), ...]``.

    The hashes and the ``# via`` annotations belong to the pin above them, and
    both are continuation lines rather than anything self-describing, so they
    can only be attributed by position.
    """
    text = LOCKFILE.read_text()
    found = list(_PIN.finditer(text))
    return [
        (m.group("name"), text[m.start() : (found[i + 1].start() if i + 1 < len(found) else -1)])
        for i, m in enumerate(found)
    ]


def _sources(block: str) -> set[str]:
    """What the ``# via`` lines of one block name, minus the requirements file.

    uv writes a single source inline (``# via kombu``) and several as a bare
    ``# via`` followed by one indented name per line, so both forms are read
    here. ``-r backend/requirements.txt`` is a direct dependency rather than
    another distribution, and is dropped.
    """
    names: set[str] = set()
    for line in re.findall(r"^\s*#\s+(.*)$", block, re.MULTILINE):
        candidate = line.removeprefix("via").strip()
        if candidate and not candidate.startswith("-r "):
            names.add(candidate)
    return names


RUNTIME = _requirements("requirements.txt")
DEV = _requirements("requirements-dev.txt")
LOCK = _lock()


def _ids(reqs: list[Requirement]) -> list[str]:
    return [req.name for req in reqs]


def _assert_floor_met(req: Requirement, source: str) -> None:
    try:
        installed = version(req.name)
    except PackageNotFoundError:  # pragma: no cover - a broken environment
        raise AssertionError(f"{req.name} is declared in {source} but not installed") from None
    assert req.specifier.contains(installed, prereleases=True), (
        f"{req.name} {installed} is installed but {source} asks for {req.specifier}"
    )


class TestEveryDeclaredFloorIsMet:
    """The installed distribution satisfies the version it is declared against."""

    @pytest.mark.parametrize("req", RUNTIME, ids=_ids(RUNTIME))
    def test_a_runtime_dependency_is_installed_at_or_above_its_floor(self, req):
        _assert_floor_met(req, "requirements.txt")

    @pytest.mark.parametrize("req", DEV, ids=_ids(DEV))
    def test_a_dev_dependency_is_installed_at_or_above_its_floor(self, req):
        _assert_floor_met(req, "requirements-dev.txt")


class TestTheFilesThemselves:
    def test_every_runtime_dependency_carries_a_floor(self):
        """An unpinned dependency resolves to whatever shipped that morning."""
        unbounded = [req.name for req in RUNTIME if not req.specifier]
        assert unbounded == []

    def test_every_dev_dependency_carries_a_floor(self):
        unbounded = [req.name for req in DEV if not req.specifier]
        assert unbounded == []

    def test_nothing_is_declared_in_both_files(self):
        """requirements-dev.txt includes the runtime file via `-r`.

        Naming a package in both means two floors to keep in step, and the
        looser one silently wins whenever pip resolves the pair.
        """
        overlap = {req.name for req in RUNTIME} & {req.name for req in DEV}
        assert overlap == set()


class TestTheLockIsWhatTheServerInstalls:
    """``requirements.lock`` against the floors it was resolved from.

    The floors are what this project *needs*; the lock is what the server
    *gets*. CI installs the floors on purpose — that is the check that keeps a
    Dependabot bump honest, and it is why the two files are not merged — so
    the lock is the one artefact nothing else exercises, and an unnoticed
    edit to it is a release that installs something the suite never saw.

    None of this proves the pinned versions work; the suite running is what
    does that, and it runs against an environment resolved from the same
    floors. What it proves is that the lock is a complete, hash-checked
    closure of those floors, which is the property `pip --require-hashes`
    depends on and the one that breaks silently.
    """

    def test_the_lock_exists(self):
        assert LOCKFILE.is_file(), (
            "regenerate with: uv pip compile backend/requirements.txt --universal "
            "--python-version 3.12 --generate-hashes -o backend/requirements.lock"
        )

    @pytest.mark.parametrize("req", RUNTIME, ids=_ids(RUNTIME))
    def test_a_runtime_dependency_is_pinned_in_the_lock(self, req):
        # A dependency added to requirements.txt and not recompiled into the
        # lock is one the server never installs — and the import error lands
        # in the API's journal at restart, after the release reported success.
        assert canonicalize_name(req.name) in LOCK, f"{req.name} is not in requirements.lock"

    @pytest.mark.parametrize("req", RUNTIME, ids=_ids(RUNTIME))
    def test_a_pin_honours_the_floor_it_was_resolved_from(self, req):
        # The direction that matters: a floor raised after the lock was last
        # compiled leaves the two disagreeing, and it is the lock that is
        # installed. This is what turns that into a red test rather than a
        # production runtime a version behind what the code assumes.
        pinned = LOCK.get(canonicalize_name(req.name))
        if pinned is None:
            pytest.skip("covered by the pinned-in-the-lock test")
        assert req.specifier.contains(pinned, prereleases=True), (
            f"requirements.lock pins {req.name} {pinned}, below the declared {req.specifier}"
        )

    def test_every_pin_carries_hashes(self):
        # `pip install --require-hashes` is all-or-nothing: one entry without
        # a hash fails the whole install, on the server, mid-release.
        unhashed = [name for name, block in _blocks() if "--hash=" not in block]
        assert unhashed == []

    def test_the_lock_is_a_closed_set(self):
        # Every `# via` names either the requirements file or another pin in
        # here. A lock that references a distribution it does not pin is not a
        # closure, and pip resolves the gap at install time — which is exactly
        # the unpinned resolution the file exists to prevent.
        dangling = {
            source
            for _, block in _blocks()
            for source in _sources(block)
            if canonicalize_name(source) not in LOCK
        }
        assert dangling == set()


def test_ci_tests_the_versions_a_release_installs():
    """P24 M17: CI installed the floors, which resolved the newest of
    everything (SQLAlchemy 2.1 while production ran 2.0), so the suite passed
    on versions no release ever ran. It installs the lock first now, as
    deploy.sh does, and the test tools on top."""
    workflow = (BACKEND.parent / ".github" / "workflows" / "ci.yml").read_text()
    lock = workflow.index("pip install --require-hashes -r requirements.lock")
    dev = workflow.index("pip install -r requirements-dev.txt")
    assert lock < dev
    deploy = (BACKEND.parent / "deploy" / "deploy.sh").read_text()
    assert '--require-hashes -r "$LOCKFILE"' in deploy
