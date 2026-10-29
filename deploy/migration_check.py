"""Decide whether gstbot-migrate should run ``alembic upgrade head`` at all.

Run as the unit's ``ExecCondition=``, from ``/opt/GSTBot/backend``.

``deploy.sh <previous-sha>`` is the documented rollback, and after any release
that added a migration it could not work: the database is stamped with a
revision the older tree does not have, ``alembic upgrade head`` stops with
"Can't locate revision", the unit fails, and gstbot-api and gstbot-worker,
which ``Requires=`` it, refuse to start — on the rollback and on every boot
after it. The incident the rollback was for gains an outage.

A database ahead of the code is the one case where not migrating is right:
the schema is newer, the README already says a downgrade is a decision to
take by hand, and every migration here is additive enough for the previous
release to run on it. So that case exits 1, which systemd treats as "skip the
unit" rather than "fail it", and dependents start. Anything else that goes
wrong — the database is down, the settings do not load — exits 255, which
fails the unit exactly as a failed ``alembic upgrade`` would.
"""
from __future__ import annotations

import os
import sys

RUN = 0
SKIP = 1
FAIL = 255


def unknown_revisions(current: set[str], known: set[str]) -> set[str]:
    """The revisions the database is on that this tree has never heard of."""
    return current - known


def main() -> int:
    sys.path.insert(0, os.getcwd())
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine

        from app.core.config import settings

        script = ScriptDirectory.from_config(Config("alembic.ini"))
        known = {rev.revision for rev in script.walk_revisions()}
        engine = create_engine(settings.database_url)
        try:
            with engine.connect() as connection:
                current = set(MigrationContext.configure(connection).get_current_heads())
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001 - every failure here is the unit's failure
        print(f"migration check failed: {exc}", file=sys.stderr)
        return FAIL

    ahead = unknown_revisions(current, known)
    if ahead:
        print(
            "the database is at " + ", ".join(sorted(ahead)) + ", which this release does "
            "not have — a rollback. Not migrating; downgrade by hand if the older "
            "code needs the older schema (deploy/README.md, Rollback).",
            file=sys.stderr,
        )
        return SKIP
    return RUN


if __name__ == "__main__":
    sys.exit(main())
