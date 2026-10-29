"""Every migration must leave a schema the release before it can run on.

Two things already depend on that and nothing checked it:

* ``deploy.sh`` runs ``alembic upgrade head`` while the previous release is
  still serving, and restarts it only afterwards. A migration that drops,
  renames or tightens a column breaks the running API for that window.
* ``deploy/migration_check.py`` makes ``deploy.sh <previous-sha>`` a working
  rollback by *not* downgrading a database that is ahead of the code — on the
  stated ground that "every migration here is additive enough for the previous
  release to run on it".

And one thing CI cannot see at all: a ``NOT NULL`` column added without a
server default migrates an empty database — CI's — and fails on the first
production table with a row in it, aborting the release.

A migration that genuinely has to contract the schema says so by setting
``DESTRUCTIVE = "<why, and which release stopped using it>"`` at module level.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

_DROPS = {"drop_column", "drop_table", "rename_table"}


def _is_false(value) -> bool:
    return isinstance(value, ast.Constant) and value.value is False


def problems(source: str) -> list[str]:
    """What in this migration's ``upgrade()`` the previous release cannot survive."""
    tree = ast.parse(source)
    declared = any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "DESTRUCTIVE" for t in node.targets)
        for node in tree.body
    )
    upgrade = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"), None
    )
    if upgrade is None:
        return []
    found: list[str] = []
    for node in ast.walk(upgrade):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        name = node.func.attr
        keywords = {k.arg: k.value for k in node.keywords}
        if name in _DROPS and not declared:
            found.append(f"line {node.lineno}: {name}")
        elif name == "alter_column" and not declared:
            if "new_column_name" in keywords:
                found.append(f"line {node.lineno}: alter_column renames a column")
            elif _is_false(keywords.get("nullable")):
                found.append(f"line {node.lineno}: alter_column makes a column NOT NULL")
            elif "type_" in keywords:
                found.append(f"line {node.lineno}: alter_column changes a column's type")
        elif name == "add_column":
            # Never excusable: it fails on production's rows whatever the reason.
            for column in (a for a in node.args if isinstance(a, ast.Call)):
                column_kw = {k.arg: k.value for k in column.keywords}
                nullable = column_kw.get("nullable")
                not_null = isinstance(nullable, ast.Constant) and nullable.value is False
                if not_null and "server_default" not in column_kw:
                    found.append(
                        f"line {node.lineno}: add_column adds a NOT NULL column with no "
                        "server_default — it migrates CI's empty tables and fails on "
                        "production's rows"
                    )
    return found


@pytest.mark.parametrize("path", sorted(VERSIONS.glob("*.py")), ids=lambda p: p.name)
def test_the_migration_leaves_a_schema_the_previous_release_can_run_on(path):
    assert problems(path.read_text()) == [], path.name


def _migration(body: str, preamble: str = "") -> str:
    return textwrap.dedent(preamble) + "\n\ndef upgrade():\n" + textwrap.indent(
        textwrap.dedent(body), "    "
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("op.drop_column('invoices', 'notes')", "drop_column"),
        ("op.drop_table('alerts')", "drop_table"),
        ("op.rename_table('alerts', 'notices')", "rename_table"),
        ("with op.batch_alter_table('t') as b:\n    b.drop_column('x')", "drop_column"),
        ("op.alter_column('t', 'x', new_column_name='y')", "renames"),
        ("op.alter_column('t', 'x', nullable=False)", "NOT NULL"),
        ("op.alter_column('t', 'x', type_=sa.Integer())", "type"),
        ("op.add_column('t', sa.Column('x', sa.Integer(), nullable=False))", "server_default"),
    ],
)
def test_the_guard_catches_what_would_break_a_release(body, expected):
    found = problems(_migration(body))
    assert len(found) == 1 and expected in found[0], found


def test_a_not_null_column_with_a_server_default_is_fine():
    body = (
        "op.add_column('t', sa.Column('x', sa.Boolean(), nullable=False,"
        " server_default=sa.false()))"
    )
    assert problems(_migration(body)) == []


def test_a_declared_contraction_is_allowed_but_a_not_null_add_never_is():
    declared = 'DESTRUCTIVE = "notes unused since 0030; dropped two releases later"'
    assert problems(_migration("op.drop_column('invoices', 'notes')", declared)) == []
    still = problems(_migration(
        "op.add_column('t', sa.Column('x', sa.Integer(), nullable=False))", declared
    ))
    assert len(still) == 1


def test_downgrades_may_drop_whatever_they_like():
    source = _migration("op.add_column('t', sa.Column('x', sa.Integer()))") + (
        "\n\ndef downgrade():\n    op.drop_column('t', 'x')\n"
    )
    assert problems(source) == []
