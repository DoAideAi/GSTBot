"""``app`` has no import cycle, counting the imports deferred into functions.

A cycle written at module level fails at import time, so nothing has to test
for one. Moving one side of it into a function body makes the import succeed
and hides the cycle: ``app.core.errors`` and ``app.core.middleware`` each
imported the other from inside a function, which coupled the two through a
private attribute (``SecurityHeadersMiddleware._BASE``) that neither module's
interface admitted to. That cycle is gone (``app.core.headers``); this keeps a
new one from arriving the same way.

Deferred imports are still allowed for other reasons — importing the Celery
app only when a task is actually queued, or looking ``redis_client.get_redis``
up late so tests can patch it. Those point one way and close no loop.
"""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


def _module_name(path: Path) -> str:
    parts = path.relative_to(APP.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _is_type_checking(node: ast.AST) -> bool:
    test = getattr(node, "test", None)
    return isinstance(node, ast.If) and (
        (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
        or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
    )


def _runtime_nodes(tree: ast.AST):
    """Every node that can execute. ``if TYPE_CHECKING:`` blocks never do —
    the models import each other there for their relationship annotations —
    so they close no loop at runtime and are left out."""
    for child in ast.iter_child_nodes(tree):
        if _is_type_checking(child):
            yield from (n for n in child.orelse for n in ast.walk(n))
            continue
        yield child
        yield from _runtime_nodes(child)


def _graph() -> dict[str, set[str]]:
    modules = {_module_name(p): p for p in APP.rglob("*.py")}
    graph: dict[str, set[str]] = {name: set() for name in modules}
    for name, path in modules.items():
        for node in _runtime_nodes(ast.parse(path.read_text(encoding="utf-8"))):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                targets = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            graph[name].update(t for t in targets if t in modules and t != name)
    return graph


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Strongly connected components with more than one module (Tarjan)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[list[str]] = []
    counter = [0]

    def visit(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                found.append(sorted(component))

    for v in graph:
        if v not in index:
            visit(v)
    return found


def test_the_sweep_sees_the_application():
    graph = _graph()
    assert "app.core.middleware" in graph
    assert "app.core.errors" in graph["app.core.middleware"]


def test_no_import_cycle_even_through_deferred_imports():
    assert _cycles(_graph()) == []


def test_a_type_checking_import_is_not_a_runtime_edge():
    tree = ast.parse(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    from app.models.user import User\n"
        "def f():\n    from app.core.errors import error_body\n"
    )
    imported = {n.module for n in _runtime_nodes(tree) if isinstance(n, ast.ImportFrom)}
    assert imported == {"typing", "app.core.errors"}


def test_a_deferred_cycle_is_noticed():
    """The detector itself, on the shape it exists to catch."""
    assert _cycles({"a": {"b"}, "b": {"a"}, "c": set()}) == [["a", "b"]]
