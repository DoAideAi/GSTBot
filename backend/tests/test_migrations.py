"""The migrations and the models, checked against each other.

Every other test in this suite runs against a schema built by
``Base.metadata.create_all``. No deployment ever does that: the server runs
``alembic upgrade head`` and the API then issues ORM queries against whatever
that produced. CI covers part of the difference already — it applies the
migrations to a real Postgres, walks them down to base and back up, and runs
``alembic check`` against the models. What none of that reaches:

- **Rolling back to a revision that is not base.** CI's round trip goes all the
  way down, where the first migration drops every table wholesale. A later
  downgrade can forget every column it added and still leave an empty database
  behind, so the step passes. But a rollback in production goes back *one*
  release, and what it has to produce is the schema the previous release ran
  on. That property is asserted here, per revision, by comparing the schema
  after ``upgrade head; downgrade R`` against the schema after plain
  ``upgrade R``.
- **A branched or orphaned history.** Two heads make ``upgrade head`` refuse to
  choose, and a revision whose parent was mistyped is skipped in silence. Both
  surface in CI as an opaque alembic error in a step near the end of the job,
  if at all; here they are a named test with the revision ids in the message.
- **Running at all before the push.** These take seconds and need nothing
  installed, so drift is caught while the change is still being written.

By default the scratch database is a throwaway SQLite file, which the
migrations support on purpose — non-native enums, ``JSON`` with a Postgres
variant, ``batch_alter_table`` for the rewrites. That much cannot see
Postgres-only behaviour, and ``batch_alter_table`` is precisely where the two
diverge: SQLite rebuilds the table, Postgres issues a real ``ALTER``. So the
URL is overridable — CI sets ``MIGRATION_TEST_DATABASE_URL`` to the Postgres
service and runs this module a second time against it, and the rollback
property is then checked on the engine that actually ships.

Alembic runs in a subprocess throughout. ``alembic/env.py`` reads
``settings.database_url`` at import, and ``settings`` is a module-level
singleton already bound to the suite's in-memory database by the time any test
imports — so in-process the migrations would either run nowhere or run over the
fixture data.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, create_engine, inspect, text

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.core.database import Base

BACKEND = Path(__file__).resolve().parents[1]

# Tables alembic owns rather than the application. Excluded from "the database
# is empty" assertions, since a downgrade to base is meant to leave it behind.
BOOKKEEPING = {"alembic_version"}

# Set by CI to the Postgres service. Unset locally, where each test gets its own
# SQLite file instead — deliberately not read through ``settings``, which
# conftest has already pinned to the suite's in-memory database.
SHARED_URL = os.environ.get("MIGRATION_TEST_DATABASE_URL")


# Applies a sequence of alembic commands in one interpreter. `alembic.ini` is
# read the same way the CLI reads it, including `prepend_sys_path`, so env.py
# resolves the URL through settings exactly as it does on the server.
_DRIVER = """
import sys
from alembic import command
from alembic.config import Config

config = Config("alembic.ini")
for step in sys.argv[1:]:
    action, revision = step.split(":", 1)
    getattr(command, action)(config, revision)
"""


def _alembic(url: str, *steps: str) -> subprocess.CompletedProcess[str]:
    """Run alembic commands against *url*, as ``"upgrade:head"`` and the like.

    Batched into a single process because every invocation pays for importing
    the application to resolve the URL — half a second each, and a test that
    upgrades, rolls back and re-upgrades pays it three times. Across this
    module that difference is the whole of its runtime.
    """
    return subprocess.run(
        [sys.executable, "-c", _DRIVER, *steps],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        timeout=300,
        # DATABASE_URL is what env.py resolves through settings, and the
        # inherited value points at the suite's in-memory database.
        env={**os.environ, "DATABASE_URL": url},
    )


def _run(url: str, *steps: str) -> None:
    """*_alembic*, insisting it worked."""
    result = _alembic(url, *steps)
    assert result.returncode == 0, f"alembic {' '.join(steps)} failed:\n{result.stderr}"


def _url_for(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"


def _script() -> ScriptDirectory:
    """The revision directory, found from anywhere.

    ``script_location = alembic`` in the ini is relative, and alembic resolves
    it against the *working directory*, not against the ini file it came from.
    The subprocess helpers above pin ``cwd`` to ``BACKEND`` and so are fine;
    this one runs in-process and inherits whatever directory pytest was
    started in. Left alone it fails from the repository root — and fails
    quietly, because ``_load_chain`` swallows the error to keep collection
    alive, leaving ``CHAIN`` empty and ``ROLLBACK_TARGETS`` collapsed to
    ``["base"]``. The rollback tests below would then still pass, having
    stopped covering every revision but the first.
    """
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(config)


def _load_chain() -> tuple[list[str], str | None]:
    """Revisions oldest-first, or the error alembic raised reading them.

    The chain is needed at import to parametrize over it, and a broken one
    makes alembic raise there — which would take collection of this whole
    module down and report it as a bare ``KeyError`` with no test name
    attached. The error is carried instead, so the module still collects and
    the test that names the problem is the one that fails.
    """
    try:
        return [rev.revision for rev in _script().walk_revisions()][::-1], None
    except Exception as exc:  # noqa: BLE001 - reported by a test, not swallowed
        return [], f"{type(exc).__name__}: {exc}"


CHAIN, CHAIN_ERROR = _load_chain()

# Every point a running deployment could be rolled back to: base, and each
# revision before the head. Rolling back *to* head is not a rollback.
ROLLBACK_TARGETS = ["base", *CHAIN[:-1]]


def _wipe(url: str) -> None:
    """Drop everything, including alembic's own bookkeeping.

    Reflection and ``drop_all`` rather than ``alembic downgrade base``, so that
    resetting between tests does not depend on the downgrades these tests
    exist to check.
    """
    engine = create_engine(url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=engine)
        metadata.drop_all(bind=engine)
    finally:
        engine.dispose()


def _table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - BOOKKEEPING
    finally:
        engine.dispose()


def _predicate(index: dict) -> str:
    """The ``WHERE`` clause of a partial index, or ``""`` for a total one.

    Both backends put it in ``dialect_options`` under their own prefix —
    ``postgresql_where`` against Postgres, ``sqlite_where`` against SQLite —
    and only one of the two is ever present. Stringified because SQLite hands
    back a ``TextClause``, which compares by identity; fingerprints are only
    ever compared against others taken from the same dialect, so the
    formatting difference between the two backends does not matter. A string
    rather than ``None`` so that index tuples stay sortable.

    Without this, ``uq_gstr_returns_business_period_type`` recreated as a
    *total* unique index would fingerprint identically to the partial one that
    migration 0002 installed — same name, same columns, same uniqueness — and
    a downgrade that quietly forbids re-importing a GSTR-2B period would pass.
    """
    options = index.get("dialect_options") or {}
    for key, value in options.items():
        if key.endswith("_where"):
            return str(value)
    return ""


def _default(column: dict) -> str:
    """A column's server-side default, or ``""`` for none.

    Migration 0003 adds ``invoices.is_capital_good`` with a ``server_default``
    so the ``NOT NULL`` can be applied to rows that already exist, and then
    drops the default in a second step — deliberately, so that an insert which
    forgets the column fails instead of quietly storing ``false``. Without this
    field, a downgrade or an edited migration that leaves the default in place
    fingerprints identically to one that removed it, and the guarantee that
    second step exists for is untested.

    Stringified, and ``""`` rather than ``None``, for the same reasons as
    ``_predicate``: the backends spell defaults differently — SQLite echoes the
    literal, Postgres returns ``false`` — and fingerprints are only ever
    compared against others taken from the same dialect.
    """
    default = column.get("default")
    return "" if default is None else str(default)


def _fingerprint(url: str) -> dict:
    """The schema as the database reports it, reduced to what a query can see.

    Names, types, nullability, server defaults, indexes and their predicates,
    uniqueness and foreign keys — not physical layout, and not the order any of
    them came back in. Two databases with equal fingerprints are
    interchangeable as far as the ORM is concerned, which is the property a
    rollback has to have.
    """
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        schema: dict = {}
        for table in sorted(set(inspector.get_table_names()) - BOOKKEEPING):
            schema[table] = {
                "columns": sorted(
                    (
                        column["name"],
                        str(column["type"]),
                        bool(column["nullable"]),
                        _default(column),
                    )
                    for column in inspector.get_columns(table)
                ),
                "indexes": sorted(
                    (
                        index["name"],
                        tuple(index["column_names"]),
                        bool(index["unique"]),
                        _predicate(index),
                    )
                    for index in inspector.get_indexes(table)
                ),
                "unique": sorted(
                    (constraint["name"], tuple(constraint["column_names"]))
                    for constraint in inspector.get_unique_constraints(table)
                ),
                "foreign_keys": sorted(
                    (
                        tuple(key["constrained_columns"]),
                        key["referred_table"],
                        tuple(key["referred_columns"]),
                    )
                    for key in inspector.get_foreign_keys(table)
                ),
            }
        return schema
    finally:
        engine.dispose()


@pytest.fixture()
def scratch(tmp_path):
    """An empty database to migrate, and empty again afterwards.

    A per-test SQLite file normally, so nothing has to be installed and tests
    cannot interfere with each other. When CI points this at Postgres there is
    only the one database, so it is wiped on both sides — on the way in because
    the previous test may have failed partway through, on the way out so the
    next module does not inherit a schema.
    """
    if SHARED_URL is None:
        yield _url_for(tmp_path / "scratch.db")
        return

    _wipe(SHARED_URL)
    try:
        yield SHARED_URL
    finally:
        _wipe(SHARED_URL)


@pytest.fixture()
def migrated(scratch) -> str:
    """*scratch*, taken to head by the real migrations."""
    _run(scratch, "upgrade:head")
    return scratch


class TestTheDeployedSchemaIsTheOneTheModelsDescribe:
    """The assertion the rest of the suite quietly assumes."""

    def test_the_migrations_leave_nothing_for_autogenerate_to_find(self, migrated):
        """A non-empty diff here is a model change that never got a migration.

        Reported as the operations alembic would generate, because that is both
        the evidence and the fix: the same list comes out of
        ``alembic revision --autogenerate`` when someone runs it.
        """
        engine = create_engine(migrated)
        try:
            with engine.connect() as connection:
                context = MigrationContext.configure(
                    connection,
                    opts={
                        # Off by default, and the difference between catching a
                        # column widened in the model only and not catching it.
                        "compare_type": True,
                        # Also off by default. 0003 adds a column with a
                        # server_default purely to backfill the existing rows
                        # and drops it again a step later, so that an insert
                        # omitting the column fails rather than silently
                        # storing false. Without this, that second step could
                        # be deleted and nothing here would notice.
                        "compare_server_default": True,
                    },
                )
                diff = compare_metadata(context, Base.metadata)
        finally:
            engine.dispose()

        assert not diff, "models and migrations have drifted:\n" + "\n".join(
            repr(op) for op in diff
        )

    def test_every_model_table_exists_after_the_migrations(self, migrated):
        # Overlaps the diff above and is kept for the failure it gives: a whole
        # table missing reads as one named absence rather than as a wall of
        # add_column operations.
        assert set(Base.metadata.tables) <= _table_names(migrated)

    def test_the_database_is_stamped_at_a_single_revision(self, migrated):
        # Two rows in alembic_version means two heads were applied, and the
        # next `upgrade head` on that database fails.
        engine = create_engine(migrated)
        try:
            with engine.connect() as connection:
                rows = connection.execute(text("SELECT version_num FROM alembic_version"))
                versions = [row[0] for row in rows]
        finally:
            engine.dispose()

        assert len(versions) == 1, f"stamped at {versions}"


class TestTheChainCanBeWalkedBothWays:
    """A release that cannot be backed out is a release that has to be fixed
    forward while it is broken."""

    @pytest.fixture()
    def script(self) -> ScriptDirectory:
        return _script()

    def test_the_revision_history_can_be_read_at_all(self):
        # First, because everything below it is parametrized or reasoned over
        # the chain this loads. A down_revision naming a revision that is not
        # there fails here, with the id in the message, rather than as an
        # unattributed KeyError out of collection.
        assert CHAIN_ERROR is None, f"alembic cannot read the history: {CHAIN_ERROR}"
        assert CHAIN, "no migrations found"

    def test_the_history_is_readable_from_any_working_directory(self, tmp_path):
        """Where pytest was started from must not change what is covered.

        ``script_location`` is relative and alembic resolves it against the
        working directory, so an in-process ``Config`` finds the revisions only
        when the caller happens to be sitting in ``backend/``. That failure is
        not loud: ``_load_chain`` catches it so collection survives, so running
        the suite from the repository root would leave ``CHAIN`` empty and the
        rollback parametrization below reduced to ``base`` alone — fewer tests,
        all of them green.
        """
        original = Path.cwd()
        os.chdir(tmp_path)
        try:
            revisions = [rev.revision for rev in _script().walk_revisions()][::-1]
        finally:
            os.chdir(original)

        assert revisions == CHAIN

    def test_every_revision_before_the_head_is_a_rollback_target(self):
        # Guards the parametrization itself rather than the migrations. The
        # targets are computed once at import from a chain that is empty when
        # loading it failed, and an empty parametrize list is not an error —
        # it is a test that silently stops running.
        expected = ["base", *CHAIN[:-1]]
        assert expected == ROLLBACK_TARGETS
        assert len(ROLLBACK_TARGETS) == len(CHAIN)

    def test_there_is_exactly_one_head(self, script):
        # Two developers branching from the same revision produces two heads,
        # and `alembic upgrade head` refuses to guess between them — so the
        # deploy fails at the migrate unit, before the API starts.
        heads = script.get_heads()
        assert len(heads) == 1, f"branched migration history: {heads}"

    def test_every_revision_file_is_in_the_chain(self):
        """A migration alembic never runs and never mentions.

        ``walk_revisions`` follows ``down_revision`` back from the head, so a
        file whose parent was mistyped — or one that was branched from and then
        rebased around — is simply not on that path. It is on disk, it is in
        the diff, it reviews as applied, and ``upgrade head`` skips it in
        silence. The count on disk is the only thing that notices.
        """
        in_chain = set(CHAIN)
        on_disk = {
            path.name
            for path in (BACKEND / "alembic" / "versions").glob("*.py")
            if not path.name.startswith("__")
        }

        assert len(in_chain) == len(on_disk), (
            f"{len(on_disk)} revision files, {len(in_chain)} in the chain: {sorted(in_chain)}"
        )

    @pytest.mark.parametrize("target", ROLLBACK_TARGETS)
    def test_rolling_back_to_a_revision_matches_never_having_passed_it(
        self, scratch, target
    ):
        """The property a downgrade is actually claiming, stated directly.

        Reaching base and finding no tables says almost nothing, because the
        first migration drops them wholesale — a later downgrade can forget
        every column it added and still leave an empty database behind. What a
        rollback has to produce is the schema the *previous release* ran on, so
        that is what is compared: the database migrated only as far as the
        target, against the same database taken to head and brought back, both
        read out of the database itself rather than out of the models.

        ``base`` is one of the targets, which covers "a full downgrade leaves
        nothing behind" as the degenerate case: the reference fingerprint of a
        database migrated to base is empty.
        """
        _run(scratch, f"upgrade:{target}")
        never_passed_it = _fingerprint(scratch)

        _run(scratch, "upgrade:head", f"downgrade:{target}")

        assert _fingerprint(scratch) == never_passed_it, (
            f"rolling back to {target} does not reproduce that revision's schema"
        )

    def test_the_chain_can_be_replayed_after_a_rollback(self, migrated):
        # Rolling back and rolling forward again is the actual sequence: a bad
        # release goes out, comes back, gets fixed, goes out again. A downgrade
        # that leaves a stray index or constraint behind passes the base test
        # above and fails here, on the re-upgrade.
        _run(migrated, "downgrade:base", "upgrade:head")

        assert set(Base.metadata.tables) <= _table_names(migrated)


class TestTheComparisonNoticesTheDifferencesItClaimsTo:
    """The rollback test is only as good as ``_fingerprint``.

    Everything above compares two fingerprints for equality, so a field the
    fingerprint does not read is a difference the rollback test cannot fail
    on — silently, and looking exactly like a pass. These build the "after"
    schema by hand, one property at a time, and check the comparison sees it.

    Always SQLite, even when the module is pointed at Postgres: what is under
    test is the reflection-to-dict step, not the migrations, and using the
    shared database here would mean wiping it out from under the fixture.
    """

    @pytest.fixture()
    def two(self, tmp_path) -> tuple[str, str]:
        return _url_for(tmp_path / "a.db"), _url_for(tmp_path / "b.db")

    @staticmethod
    def _apply(url: str, *statements: str) -> None:
        engine = create_engine(url)
        try:
            with engine.begin() as connection:
                for statement in statements:
                    connection.execute(text(statement))
        finally:
            engine.dispose()

    def test_two_databases_built_the_same_way_fingerprint_the_same(self, two):
        # The control. Without it, a fingerprint that differed on every
        # comparison would pass every test below and fail every real one.
        first, second = two
        for url in two:
            self._apply(url, "CREATE TABLE t (id INTEGER PRIMARY KEY, name VARCHAR(10))")

        assert _fingerprint(first) == _fingerprint(second)

    def test_a_dropped_where_clause_is_noticed(self, two):
        """The one that motivated the field, and migration 0002's whole point.

        A downgrade that recreates ``uq_gstr_returns_business_period_type``
        without its predicate reads as the same index by name, columns and
        uniqueness, and turns re-importing a regenerated GSTR-2B period from a
        supported operation into an integrity error.
        """
        partial, total = two
        for url in two:
            self._apply(url, "CREATE TABLE t (id INTEGER PRIMARY KEY, deleted_at DATETIME)")
        self._apply(partial, "CREATE UNIQUE INDEX ix ON t (id) WHERE deleted_at IS NULL")
        self._apply(total, "CREATE UNIQUE INDEX ix ON t (id)")

        assert _fingerprint(partial) != _fingerprint(total)

    @pytest.mark.parametrize(
        ("difference", "after"),
        [
            ("a column left behind", "CREATE TABLE t (id INTEGER PRIMARY KEY, extra INTEGER)"),
            ("a column renamed", "CREATE TABLE t (ident INTEGER PRIMARY KEY)"),
            ("a widened type", "CREATE TABLE t (id INTEGER PRIMARY KEY, name VARCHAR(20))"),
            ("nullability", "CREATE TABLE t (id INTEGER PRIMARY KEY, name VARCHAR(10))"),
            (
                "a table left behind",
                "CREATE TABLE t (id INTEGER PRIMARY KEY); CREATE TABLE u (id INTEGER)",
            ),
        ],
    )
    def test_the_schema_differences_a_downgrade_leaves_behind_are_noticed(
        self, two, difference, after
    ):
        # The before is the same in every case; each `after` gets one property
        # wrong, in the way a downgrade that forgot a step would.
        before, mutated = two
        self._apply(
            before, "CREATE TABLE t (id INTEGER PRIMARY KEY, name VARCHAR(10) NOT NULL)"
        )
        self._apply(mutated, *after.split("; "))

        assert _fingerprint(before) != _fingerprint(mutated), difference

    def test_a_server_default_left_behind_is_noticed(self, two):
        """0003's second ``batch_alter_table``, stated as a property.

        That step exists only to drop the ``server_default`` the step before it
        added, and deleting it leaves a schema that still satisfies every other
        field here — same column, same type, same ``NOT NULL``. What changes is
        that an insert which forgets ``is_capital_good`` starts succeeding with
        ``false`` instead of being rejected, which is the bug the migration's
        own comment says the step prevents.
        """
        defaulted, bare = two
        self._apply(
            defaulted,
            "CREATE TABLE t (id INTEGER PRIMARY KEY, flag BOOLEAN NOT NULL DEFAULT 0)",
        )
        self._apply(bare, "CREATE TABLE t (id INTEGER PRIMARY KEY, flag BOOLEAN NOT NULL)")

        assert _fingerprint(defaulted) != _fingerprint(bare)

    def test_a_dropped_index_is_noticed(self, two):
        indexed, bare = two
        for url in two:
            self._apply(url, "CREATE TABLE t (id INTEGER PRIMARY KEY, name VARCHAR(10))")
        self._apply(indexed, "CREATE INDEX ix ON t (name)")

        assert _fingerprint(indexed) != _fingerprint(bare)

    def test_a_dropped_foreign_key_is_noticed(self, two):
        constrained, loose = two
        for url in two:
            self._apply(url, "CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        self._apply(
            constrained,
            "CREATE TABLE t (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent (id))",
        )
        self._apply(loose, "CREATE TABLE t (id INTEGER PRIMARY KEY, parent_id INTEGER)")

        assert _fingerprint(constrained) != _fingerprint(loose)

    def test_alembics_own_table_is_not_part_of_the_comparison(self, two):
        """Otherwise every rollback test fails on the version number.

        ``upgrade R`` leaves ``alembic_version`` holding R, and so does
        ``upgrade head; downgrade R`` — but the table itself only exists once
        alembic has run, and the base case compares against a database that
        never had it. It is excluded by name; this is the assertion that the
        exclusion is wired into the fingerprint and not only into
        ``_table_names``.
        """
        stamped, clean = two
        for url in two:
            self._apply(url, "CREATE TABLE t (id INTEGER PRIMARY KEY)")
        self._apply(stamped, "CREATE TABLE alembic_version (version_num VARCHAR(32))")

        assert _fingerprint(stamped) == _fingerprint(clean)


class TestTheMigrationsRunWhereTheyAreAimed:
    """env.py resolves the URL through settings rather than alembic.ini, so
    that the deployment and the application cannot be pointed at different
    databases. That indirection is only safe if it actually works."""

    def test_the_url_comes_from_the_environment(self, tmp_path):
        """The whole file is built on this, and it is worth one direct test.

        If ``DATABASE_URL`` were ignored — a stray ``sqlalchemy.url`` in
        alembic.ini would do it — every upgrade above would run somewhere else
        and every assertion about the result would be about a database these
        tests never made.

        Always SQLite, even when the rest of the module is pointed at Postgres:
        the assertion is that alembic created a database exactly where it was
        told to, and a file either appears at that path or it does not.
        """
        path = tmp_path / "aimed.db"
        assert not path.exists()

        _run(_url_for(path), "upgrade:head")

        assert path.exists(), "alembic did not migrate the database it was given"
        assert "businesses" in _table_names(_url_for(path))

    def test_alembic_ini_does_not_hardcode_a_url(self):
        # The other half of the same guarantee. A value here silently wins over
        # nothing, and `set_main_option` in env.py is what overrides it — so an
        # ini URL only matters when env.py changes, which is exactly when
        # nobody is looking at it.
        ini = (BACKEND / "alembic.ini").read_text()
        setting = [
            line for line in ini.splitlines() if line.strip().startswith("sqlalchemy.url")
        ]
        assert setting == ["sqlalchemy.url ="], setting


class TestReferralVisitsAreUnique:
    """0013: one referral row per (code, visitor), duplicates removed first."""

    def test_existing_duplicates_collapse_to_the_earliest_and_the_constraint_holds(self, scratch):
        import sqlalchemy as sa

        _run(scratch, "upgrade:0012")
        engine = sa.create_engine(scratch)
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO businesses (id, legal_name, plan, is_active) "
                "VALUES (1, 'Ref Co', 'FREE', true)"
            ))
            conn.execute(sa.text(
                "INSERT INTO users (id, email, hashed_password, business_id, role, is_active) "
                "VALUES (1, 'ref@example.com', 'x', 1, 'OWNER', true)"
            ))
            for visitor in ("aaa", "aaa", "aaa", "bbb"):
                conn.execute(
                    sa.text(
                        "INSERT INTO referrals (referral_code, referrer_user_id, "
                        "visitor_ip_hash, converted) VALUES ('CODE', 1, :v, false)"
                    ),
                    {"v": visitor},
                )
        engine.dispose()

        _run(scratch, "upgrade:head")
        engine = sa.create_engine(scratch)
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text("SELECT id, visitor_ip_hash FROM referrals ORDER BY id")
            ).all()
        assert [(r.id, r.visitor_ip_hash) for r in rows] == [(1, "aaa"), (4, "bbb")]
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO referrals (referral_code, referrer_user_id, visitor_ip_hash, "
                "converted) VALUES ('CODE', 1, 'aaa', false)"
            ))
        engine.dispose()

        _run(scratch, "downgrade:0012")


class TestTheOauthIdentityMigrationCleansUpFirst:
    """0020 builds a unique index on (oauth_provider, oauth_id). On a database
    that already holds an empty id or one identity on two users, building it
    would fail the deploy — so the migration clears those links first."""

    def test_empty_and_duplicate_links_are_cleared_and_the_index_then_holds(self, scratch):
        import sqlalchemy as sa

        _run(scratch, "upgrade:0019")
        engine = sa.create_engine(scratch)
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO businesses (id, legal_name, plan, is_active, created_at, updated_at) "
                # TRUE, not 1: Postgres will not put an integer in a boolean,
                # and CI re-runs this module there. SQLite takes either.
                "VALUES (1, 'B', 'free', TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            for uid, email, provider, oid in [
                (1, "first@x.com", "google", "g-1"),
                (2, "dup@x.com", "google", "g-1"),
                (3, "empty@x.com", "github", ""),
                (4, "password@x.com", None, None),
            ]:
                conn.execute(
                    sa.text(
                        "INSERT INTO users (id, business_id, email, role, is_active, "
                        "oauth_provider, oauth_id, created_at, updated_at) VALUES "
                        "(:id, 1, :email, 'OWNER', TRUE, :p, :o, "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"id": uid, "email": email, "p": provider, "o": oid},
                )
        engine.dispose()

        _run(scratch, "upgrade:0020")

        engine = sa.create_engine(scratch)
        with engine.connect() as conn:
            rows = dict(
                (r.id, (r.oauth_provider, r.oauth_id))
                for r in conn.execute(sa.text("SELECT id, oauth_provider, oauth_id FROM users"))
            )
        engine.dispose()
        assert rows == {
            1: ("google", "g-1"),  # the earliest keeps the identity
            2: (None, None),       # the later duplicate is unlinked, not deleted
            3: (None, None),       # "" was never an identity
            4: (None, None),
        }
