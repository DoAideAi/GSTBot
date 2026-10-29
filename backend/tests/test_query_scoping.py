"""Every query over a business-scoped table names the business it reads for.

The behavioural sweeps — ``test_tenancy_contract.py``, ``test_active_business_
contract.py`` — prove it of every *route*: a rival's row 404s, a switched
request never sees the home books. What they cannot reach is a query that no
route runs. A service function called only from a Celery task, or one branch of
a helper the route tests never take, can drop the ``business_id`` predicate and
pass both sweeps, because nothing they drive gets there.

So this file reads the source instead. Every ``select``/``update``/``delete``
statement in ``app/`` that touches a table carrying ``BusinessScopedMixin`` must
compare ``business_id`` somewhere in the statement — directly, or through a
``*conditions`` list built in the same function that does. The handful that
deliberately read across every tenant are listed by name with the reason, so
a new one is a decision made in this file rather than a query nobody noticed.

Static and therefore blunt: it cannot tell a predicate that is *correct* from
one that is *present*, and the behavioural sweeps remain what proves the former.
What it catches is the absence, which is the case those sweeps are blind to.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import app.models  # noqa: F401 - maps every model so the registry is complete
from app.core.database import Base
from app.models.mixins import BusinessScopedMixin

APP = Path(__file__).resolve().parents[1] / "app"

# The tables whose every row belongs to one tenant, read off the registry so a
# new scoped model is swept the moment it is mapped.
SCOPED_MODELS = frozenset(
    mapper.class_.__name__
    for mapper in Base.registry.mappers
    if issubclass(mapper.class_, BusinessScopedMixin)
)

# Queries that read across every tenant on purpose. Keyed by file and the
# function the statement sits in; the value is why. Anything not here that
# omits the predicate fails, which is the point — this list is the review.
CROSS_TENANT_BY_DESIGN: dict[tuple[str, str], str] = {
    ("services/alert_delivery.py", "_send_pending_alerts"): (
        "The digest is the one place the product loops over every business "
        "at once: it finds which tenants have something to send, then reads "
        "and stamps their alerts by id. The per-tenant scoping happens on "
        "the business rows, not on the alert rows."
    ),
    ("services/invoice_service.py", "reap_stalled_parses"): (
        "Whether a parse stalled is a property of the worker that died, not "
        "of whose invoice it was. The sweep fails every stranded row in one "
        "statement rather than one per tenant."
    ),
    ("services/invoice_service.py", "lost_uploads"): (
        "The other half of the stall sweep: uploads whose queued parse never "
        "ran, found across every tenant for the same reason."
    ),
    # The parse's own row, addressed by the id it was handed. The worker has an
    # invoice id and nothing else (Celery carries no tenant), and the row was
    # put on the queue by a request that had already scoped it. These are the
    # claim, the ownership re-check and the write-back of that one row.
    ("tasks/invoice_tasks.py", "parse_invoice_task"): (
        "The worker's claim on the row it was queued for, by id."
    ),
    ("tasks/invoice_tasks.py", "_release_claim"): (
        "Hands the worker's claimed row back, by the id it claimed."
    ),
    ("services/invoice_service.py", "_still_processing"): (
        "Re-reads the parse's own row under a lock to see it still owns it."
    ),
    ("services/invoice_service.py", "_record_failure"): (
        "Marks the parse's own row failed, only if it is still processing."
    ),
}

_QUERY_BUILDERS = frozenset({"select", "update", "delete"})


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _compares_business_id(node: ast.AST) -> bool:
    """Is ``<Model>.business_id`` compared or ``.in_``-ed anywhere in *node*?"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Compare):
            operands = [sub.left, *sub.comparators]
            if any(isinstance(o, ast.Attribute) and o.attr == "business_id" for o in operands):
                return True
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr in {"in_", "is_"}
            and isinstance(sub.func.value, ast.Attribute)
            and sub.func.value.attr == "business_id"
        ):
            return True
    return False


def _enclosing(node: ast.AST, kind: type) -> ast.AST | None:
    while node is not None:
        node = getattr(node, "parent", None)
        if isinstance(node, kind):
            return node
    return None


def _starred_lists(stmt: ast.stmt) -> set[str]:
    """Names unpacked with ``*`` into a ``.where(...)`` in *stmt*."""
    return {
        s.value.id
        for s in ast.walk(stmt)
        if isinstance(s, ast.Starred) and isinstance(s.value, ast.Name)
    }


def _list_scopes_business(function: ast.AST, name: str) -> bool:
    """Does the list *name* built in *function* compare ``business_id``?

    Follows one level of aliasing — ``conditions = list(scoped)`` — because
    that is how the alerts list is written.
    """
    for sub in ast.walk(function):
        if not isinstance(sub, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in sub.targets):
            continue
        if _compares_business_id(sub.value):
            return True
        for alias in _names_in(sub.value) - {name}:
            if _list_scopes_business(function, alias):
                return True
    return False


def _scoped_statements() -> list[tuple[str, str, int, ast.stmt]]:
    """Every statement in ``app/`` that builds a query over a scoped model."""
    found: list[tuple[str, str, int, ast.stmt]] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                child.parent = parent
        seen: set[int] = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id not in _QUERY_BUILDERS:
                continue
            if not (_names_in(node) & SCOPED_MODELS):
                continue
            stmt = _enclosing(node, ast.stmt)
            if stmt.lineno in seen:
                continue
            seen.add(stmt.lineno)
            function = _enclosing(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
            fname = function.name if function is not None else "<module>"
            found.append((str(path.relative_to(APP)), fname, stmt.lineno, stmt))
    return found


STATEMENTS = _scoped_statements()


def _is_scoped(stmt: ast.stmt) -> bool:
    if _compares_business_id(stmt):
        return True
    function = _enclosing(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
    return function is not None and any(
        _list_scopes_business(function, name) for name in _starred_lists(stmt)
    )


class TestTheSweepIsLookingAtSomething:
    def test_the_registry_yields_the_scoped_tables(self):
        assert {"Invoice", "Alert", "Supplier", "GSTRReturn", "ReconciliationRun"} <= SCOPED_MODELS

    def test_the_walk_found_the_queries(self):
        # Far more than the allowlist, or the sweep has stopped seeing the
        # routers and services it exists to read.
        assert len(STATEMENTS) > 40

    def test_every_allowlisted_query_still_exists(self):
        # A stale entry is a query that was scoped — or deleted — while its
        # exemption stayed behind, ready to cover the next one written there.
        present = {(path, fname) for path, fname, _, _ in STATEMENTS}
        stale = set(CROSS_TENANT_BY_DESIGN) - present
        assert not stale, f"exemptions for queries that no longer exist: {sorted(stale)}"

    def test_every_allowlisted_query_is_actually_unscoped(self):
        # The other direction: an exemption on a query that names the
        # business would let the predicate be removed later without a test
        # going red.
        #
        # ``select(Alert.business_id)`` still counts as unscoped: it names the
        # column without filtering on it, which is exactly what a "which
        # tenants have something" query looks like.
        for path, fname, _, stmt in STATEMENTS:
            if (path, fname) in CROSS_TENANT_BY_DESIGN:
                assert not _is_scoped(stmt), (
                    f"{path}::{fname} is exempted but scoped; drop the exemption"
                )


@pytest.mark.parametrize(
    "path, fname, lineno, stmt",
    STATEMENTS,
    ids=[f"{p}::{f}:{n}" for p, f, n, _ in STATEMENTS],
)
def test_the_query_names_the_business_it_reads_for(path, fname, lineno, stmt):
    if (path, fname) in CROSS_TENANT_BY_DESIGN:
        pytest.skip(CROSS_TENANT_BY_DESIGN[(path, fname)])
    assert _is_scoped(stmt), (
        f"app/{path}:{lineno} in {fname}() queries a business-scoped table "
        "without comparing business_id. Add the predicate, or — if it must "
        "read across tenants — list it in CROSS_TENANT_BY_DESIGN with why."
    )
