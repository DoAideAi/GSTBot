"""A small, targeted mutation tester.

Line coverage says a line *ran*. It does not say that anything would have
noticed if the line were wrong. At 99% coverage that distinction is the only
one left worth measuring: a suite can execute every branch of the GSTIN check
digit and still pass if the modulus changes, and the way to find out is to
change the modulus and see whether anything goes red.

So: parse a module, enumerate every place a plausible one-character bug could
live, and for each one produce that module with exactly that bug in it and run
the tests that are supposed to cover it. A mutant the suite fails on is
*killed*. A mutant it still passes is *survived*, and a survivor is either a
missing assertion or — occasionally, and this is why it is worth running — a
line whose behaviour nobody has actually decided on.

Why not mutmut: the operator set here is deliberately small and the test
selection is explicit rather than coverage-derived, which is what makes a run
take a minute instead of an evening. Each target names the test files that are
supposed to cover it, and that mapping is itself an assertion — if a survivor
turns out to be killed by some other file's tests, the target was wrong about
where its coverage comes from.

Usage::

    python -m tools.mutation --target gstin
    python -m tools.mutation --all --jobs 8
    python -m tools.mutation --module app/core/sanitize.py --tests tests/test_sanitize.py

Nothing here imports the application, and the mutated copy is written into a
temporary tree rather than over the working copy — an interrupted run cannot
leave a mutant behind in the repo.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

# Ordering comparisons get two mutants each: the strict negation, which no
# correct test suite can miss, and the boundary shift (`<` to `<=`), which is
# the off-by-one that actually happens. A suite that kills the first and not
# the second is asserting the direction of a threshold but not its edge.
_COMPARE: dict[type[ast.cmpop], tuple[type[ast.cmpop], ...]] = {
    ast.Eq: (ast.NotEq,),
    ast.NotEq: (ast.Eq,),
    ast.Lt: (ast.GtE, ast.LtE),
    ast.LtE: (ast.Gt, ast.Lt),
    ast.Gt: (ast.LtE, ast.GtE),
    ast.GtE: (ast.Lt, ast.Gt),
    ast.Is: (ast.IsNot,),
    ast.IsNot: (ast.Is,),
    ast.In: (ast.NotIn,),
    ast.NotIn: (ast.In,),
}

_BINARY: dict[type[ast.operator], tuple[type[ast.operator], ...]] = {
    ast.Add: (ast.Sub,),
    ast.Sub: (ast.Add,),
    ast.Mult: (ast.Div,),
    ast.Div: (ast.Mult,),
    ast.FloorDiv: (ast.Div,),
    ast.Mod: (ast.FloorDiv,),
    ast.Pow: (ast.Mult,),
}

_SYMBOL: dict[type[ast.AST], str] = {
    ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
    ast.Gt: ">", ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not",
    ast.In: "in", ast.NotIn: "not in",
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**",
    ast.And: "and", ast.Or: "or",
}


def _symbol(op: ast.AST) -> str:
    return _SYMBOL.get(type(op), type(op).__name__)


def _literal_int(node: ast.AST) -> int | None:
    """*node* as the integer it literally is, or None.

    Booleans are excluded despite being ints: `rsplit(sep, True)` is legal and
    means one split, but it is not something to reason about silently.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return None if isinstance(node.value, bool) else node.value
    # `-1` is a unary minus applied to `1`, not a negative literal.
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and (value := _literal_int(node.operand)) is not None
    ):
        return -value
    return None


def _inert_maxsplit(node: ast.Subscript) -> ast.AST | None:
    """The maxsplit of *node*, when changing it cannot change the result.

    That is `s.rsplit(sep, n)[-1]` and `s.split(sep, n)[0]` for a literal
    ``n >= 1``. Returns the argument node itself so the caller can skip that
    one child by identity; None means there is nothing to spare here.
    """
    call = node.value
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        return None
    if call.func.attr not in ("split", "rsplit"):
        return None

    maxsplit: ast.AST | None = call.args[1] if len(call.args) >= 2 else None
    if maxsplit is None:
        maxsplit = next(
            (kw.value for kw in call.keywords if kw.arg == "maxsplit"), None
        )
    if maxsplit is None:
        return None

    # `maxsplit=0` is the exception that makes the check necessary: it does no
    # splitting at all, so shifting it to 1 genuinely changes the result.
    count = _literal_int(maxsplit)
    if count is None or count < 1:
        return None

    wanted = -1 if call.func.attr == "rsplit" else 0
    return maxsplit if _literal_int(node.slice) == wanted else None


@dataclass(frozen=True)
class Mutation:
    """One candidate bug: what changed, where, and how to describe it."""

    index: int
    lineno: int
    operator: str
    before: str
    after: str

    def describe(self) -> str:
        return f"line {self.lineno}: {self.operator} {self.before!r} -> {self.after!r}"


class _Engine(ast.NodeTransformer):
    """Enumerates mutation sites, and applies exactly one of them.

    Collecting and applying run through the same traversal so that a site's
    index means the same thing in both passes — which is what lets a mutant be
    identified by an integer and reproduced later.
    """

    def __init__(self, target: int | None = None) -> None:
        self.target = target
        self.sites: list[Mutation] = []
        self.applied: Mutation | None = None
        self._counter = 0

    # -- site bookkeeping ---------------------------------------------------

    def _site(self, node: ast.AST, operator: str, before: str, after: str) -> bool:
        index = self._counter
        self._counter += 1
        mutation = Mutation(
            index=index,
            lineno=getattr(node, "lineno", 0),
            operator=operator,
            before=before,
            after=after,
        )
        if self.target is None:
            self.sites.append(mutation)
            return False
        if index == self.target:
            self.applied = mutation
            return True
        return False

    # -- things that must not be mutated ------------------------------------
    #
    # Annotations are skipped throughout. The package runs with `from __future__
    # import annotations`, so an annotation is an unevaluated string at runtime
    # and changing one cannot change behaviour: every such mutant would survive,
    # and a survivor that no test could possibly kill is noise that hides the
    # survivors that mean something.

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        if node.value is not None:
            node.value = self.visit(node.value)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:
        return node

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        node.args.defaults = [self.visit(d) for d in node.args.defaults]
        node.args.kw_defaults = [
            self.visit(d) if d is not None else None for d in node.args.kw_defaults
        ]
        node.body = [self.visit(stmt) for stmt in node.body]
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._visit_function(node)

    # Splitting a string and taking the piece at the far end is the one place a
    # number here changes nothing at all. `s.rsplit(sep, n)[-1]` is the same
    # string for every n >= 1, because the extra splits all land to the *left*
    # of the piece being taken; `s.split(sep, n)[0]` is the mirror of it. So
    # shifting that maxsplit produces a mutant no test can kill, and it is a
    # common enough idiom — `safe_filename` and `safe_extension` both use it —
    # that leaving it in puts permanent survivors in the report. Two of them
    # were enough to make the sanitize run look like it had found something.
    #
    # Only the maxsplit is spared, and only when the index is the literal that
    # makes it inert. The index itself is still mutated, so a `[-1]` that
    # should have been `[0]` dies exactly as it did before.

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        inert = _inert_maxsplit(node)
        if inert is None:
            self.generic_visit(node)
            return node

        call = node.value
        assert isinstance(call, ast.Call)  # established by _inert_maxsplit
        call.func = self.visit(call.func)
        call.args = [arg if arg is inert else self.visit(arg) for arg in call.args]
        call.keywords = [
            keyword if keyword.value is inert else self.visit(keyword)
            for keyword in call.keywords
        ]
        node.slice = self.visit(node.slice)
        return node

    # -- the operators themselves -------------------------------------------

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        for position, op in enumerate(list(node.ops)):
            for replacement in _COMPARE.get(type(op), ()):
                if self._site(node, "comparison", _symbol(op), _symbol(replacement())):
                    node.ops[position] = replacement()
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        for replacement in _BINARY.get(type(node.op), ()):
            if self._site(node, "arithmetic", _symbol(node.op), _symbol(replacement())):
                node.op = replacement()
        return node

    def visit_AugAssign(self, node: ast.AugAssign) -> ast.AST:
        node.value = self.visit(node.value)
        for replacement in _BINARY.get(type(node.op), ()):
            symbol = _symbol(node.op)
            if self._site(node, "augmented", f"{symbol}=", f"{_symbol(replacement())}="):
                node.op = replacement()
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        replacement = ast.Or if isinstance(node.op, ast.And) else ast.And
        if self._site(node, "logical", _symbol(node.op), _symbol(replacement())):
            node.op = replacement()
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        self.generic_visit(node)
        # Dropping the `not` rather than adding one: a condition that is never
        # asserted in both directions dies here and nowhere else.
        if isinstance(node.op, ast.Not) and self._site(node, "negation", "not x", "x"):
            return node.operand
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        # bool before int: `isinstance(True, int)` is true, and `True + 1` is a
        # far less interesting mutant than `False`.
        if isinstance(node.value, bool):
            if self._site(node, "boolean", repr(node.value), repr(not node.value)):
                return ast.Constant(value=not node.value)
            return node
        if isinstance(node.value, int):
            shifted = node.value + 1
            if self._site(node, "number", repr(node.value), repr(shifted)):
                return ast.Constant(value=shifted)
        # Strings and floats are left alone: a mutated error message is not a
        # bug anyone should be forced to assert on, and a shifted float is
        # indistinguishable from rounding in code that deals in money.
        return node


def mutations(source: str) -> list[Mutation]:
    """Every mutation site in *source*, in a stable order."""
    engine = _Engine()
    engine.visit(ast.parse(source))
    return engine.sites


def apply(source: str, index: int) -> tuple[str, Mutation]:
    """*source* with mutation *index* applied, and the mutation that was applied."""
    engine = _Engine(target=index)
    tree = engine.visit(ast.parse(source))
    if engine.applied is None:
        raise IndexError(f"no mutation with index {index}")
    return ast.unparse(ast.fix_missing_locations(tree)), engine.applied


def normalize(source: str) -> str:
    """*source* round-tripped through the AST, with no mutation applied.

    This is what a mutant is compared against. Running the suite on it first
    separates "the tests caught the bug" from "``ast.unparse`` dropped
    something the module needed", which would otherwise read as a perfect
    mutation score.
    """
    return ast.unparse(ast.parse(source))


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """A module, and the test files that claim to cover it."""

    name: str
    module: str
    tests: tuple[str, ...]


# Ordered cheapest-first, so an `--all` run that is going to fail tends to fail
# early. The selection is the logic where a silent wrong answer costs money or
# leaks data, rather than every module in the package: mutating a router mostly
# re-tests FastAPI.
TARGETS: tuple[Target, ...] = (
    Target("ratespec", "app/core/ratespec.py", ("tests/test_rate_limit.py",)),
    Target("sanitize", "app/core/sanitize.py", ("tests/test_sanitize.py",)),
    Target("gstin", "app/services/gstin.py", ("tests/test_gstin.py",)),
    Target(
        "gstr2b",
        "app/services/gstr2b.py",
        (
            "tests/test_gstr2b.py",
            "tests/test_gstr2b_edges.py",
            # Credit and debit notes are a separate document section of the
            # 2B, and only this file parses one.
            "tests/test_gstr2b_notes.py",
            # The overflow rails on the parsed amounts: the only tests that
            # feed the parser a figure too large to be money.
            "tests/test_money_bounds.py",
            # The edges the four above read through rather than at: the row the
            # header search gives up at, the rupee the refusal begins on, and
            # the cell a footer's label lands in.
            "tests/test_gstr2b_boundaries.py",
        ),
    ),
    Target(
        "invoice_parser",
        "app/services/invoice_parser.py",
        (
            "tests/test_invoice_parser.py",
            "tests/test_invoice_parser_edges.py",
            # The format corpus. The label regexes look covered without it,
            # because the other two files ride on one sample invoice each.
            "tests/test_invoice_formats.py",
            "tests/test_money_bounds.py",
            # The boundaries the three files above read *through* rather than
            # at: the character a column reaches to, the length a field is cut
            # at, the rupee a footing check lets pass.
            "tests/test_invoice_parser_boundaries.py",
        ),
    ),
    Target(
        "supplier_score",
        "app/services/supplier_score.py",
        (
            "tests/test_supplier_score.py",
            # Scores are read back out of a reconciliation run, and the
            # zero-invoice supplier only ever arises there.
            "tests/test_reconciliation_edges.py",
        ),
    ),
    Target("security", "app/core/security.py", ("tests/test_security.py",)),
    # The calendar every deadline in the product is derived from. Its coverage
    # is split three ways and the split is the point: the financial-year
    # arithmetic is only ever exercised through s.16(4), and ``ist_date`` only
    # through a filing read back out of the column it was written to. Listed
    # here so that stays true — dropping either file takes the score with it.
    Target(
        "gst_calendar",
        "app/services/gst_calendar.py",
        (
            "tests/test_gst_calendar.py",
            "tests/test_itc_deadline.py",
            "tests/test_filing_record.py",
        ),
    ),
    Target("itc_deadline", "app/services/itc_deadline.py", ("tests/test_itc_deadline.py",)),
    # Money the user is asked to pay that no invoice states: unlike a tax
    # split, nothing downstream re-derives a fee or an interest figure, so a
    # wrong one is never contradicted by anything — it is simply paid.
    #
    # Tops out at 43/45. The two it cannot reach are both edges of the same
    # guard in ``interest`` — zero days and zero tax each multiply out to zero
    # whether the guard catches them or not — so no test can tell the mutant
    # from the original. See the docstring there.
    Target("late_fee", "app/services/late_fee.py", ("tests/test_late_fee.py",)),
    # The tax split and the invoice the GPT's generateInvoice action returns.
    # Not test_gpt_actions.py, although it covers this module too: it reads
    # frontend/src/lib/hsnData.js, which a workspace does not hold, so the
    # round-trip refuses it before a single mutant runs.
    #
    # The four that survive are equivalent, and each is noted at its line:
    # ``frozen=True`` on the three dataclasses, which nothing assigns to, and
    # the paise multiplier in ``amount_in_words``.
    Target(
        "gst_calculator",
        "app/services/gst_calculator.py",
        ("tests/test_data_flow_calculator.py",),
    ),
    Target(
        "itc",
        "app/services/itc.py",
        (
            "tests/test_itc.py",
            # The ineligible-ITC reversal reached through a filing, which is
            # the only path that carries a return period into the ledger.
            "tests/test_filing_journeys.py",
            # ``purchases_outside_periods`` has exactly one caller — the
            # s.16(4) sweep — and this is the only file that runs it. Without
            # it the query's own narrowing has no test at all, and the three
            # mutants in it survived for want of a caller.
            "tests/test_itc_deadline.py",
            # The DUPLICATE exclusion from ``_purchases``: a duplicate invoice
            # must not inflate the available credit pool.
            "tests/test_duplicate_exclusion.py",
        ),
        # Tops out at 164/171. The seven are all guards against a value the
        # column types make impossible (``x or 0`` on a NOT NULL money column)
        # or an equal case that computes the same answer either way — adding a
        # zero-tax invoice to a running total, or scaling a split by one.
    ),
    Target(
        "filing",
        "app/services/filing.py",
        (
            "tests/test_filing.py",
            # A seventh of this module — the GSTR-1 and 3B section assembly —
            # is only ever run by writing a return and reading it back, and
            # test_filing.py never does. Without this file every mutant in
            # those lines survives for want of a caller, not an assertion.
            "tests/test_filing_record.py",
            # The edges the two above read through rather than at: the day a
            # return is late on, the day it becomes overdue, and the defaults
            # a report and a frozen value object start from.
            "tests/test_filing_boundaries.py",
        ),
    ),
    Target(
        "reconciliation",
        "app/services/reconciliation.py",
        ("tests/test_reconciliation.py", "tests/test_reconciliation_edges.py"),
    ),
)

TARGETS_BY_NAME = {target.name: target for target in TARGETS}


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

KILLED = "killed"
SURVIVED = "survived"
TIMEOUT = "timeout"

# What gets copied into a workspace. The suite's conftest points UPLOAD_DIR at
# a fresh temporary directory and the database at in-memory SQLite, so a
# workspace needs the code and nothing else.
_WORKSPACE_CONTENTS = ("app", "tests", "pyproject.toml")


@dataclass
class MutantResult:
    index: int
    lineno: int
    operator: str
    before: str
    after: str
    status: str

    @property
    def killed(self) -> bool:
        # A mutant that hangs has been detected just as surely as one that
        # fails an assertion — an infinite loop is not a passing test.
        return self.status in (KILLED, TIMEOUT)


@dataclass
class Report:
    target: str
    module: str
    tests: list[str]
    results: list[MutantResult] = field(default_factory=list)

    @property
    def survivors(self) -> list[MutantResult]:
        return [r for r in self.results if not r.killed]

    @property
    def score(self) -> float:
        if not self.results:
            return 1.0
        return sum(r.killed for r in self.results) / len(self.results)

    def summary(self) -> str:
        killed = sum(r.killed for r in self.results)
        return (
            f"{self.target}: {killed}/{len(self.results)} killed "
            f"({self.score * 100:.1f}%)"
        )


def _make_workspace(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for item in _WORKSPACE_CONTENTS:
        source = BACKEND / item
        destination = root / item
        if source.is_dir():
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
            )
        else:
            shutil.copy2(source, destination)
    return root


def _write_module(workspace: Path, relative: str, source: str) -> None:
    """Write *source* into *workspace* so that the next run actually loads it.

    Writing the file is not enough. CPython validates cached bytecode against
    the source's ``(mtime, size)``, and it stores the mtime at one-second
    resolution — while a mutant is a *one-character* change to the same file,
    so the size is usually identical too, and the writes here happen
    milliseconds apart. When both match, the interpreter reuses the ``.pyc``
    from the previous write and runs code that was never mutated. The tests
    then pass, and the mutant is reported SURVIVED.

    That is the worst failure this tool has: it is silent, it is intermittent
    (it depends on which side of a second boundary two writes land), and it
    points the wrong way — inventing a hole in the suite rather than hiding
    one. It was found as a `+` -> `-` in ``escape_like`` that "survived" a test
    that calls it directly, which is impossible: the mutant does not typecheck
    at runtime, so any call at all raises.

    Dropping the one stale cache entry is enough, and leaves the rest of the
    application's bytecode cached — which is most of what a run spends its
    time on.
    """
    path = workspace / relative
    path.write_text(source)
    Path(importlib.util.cache_from_source(str(path))).unlink(missing_ok=True)


def _run_tests(workspace: Path, tests: tuple[str, ...], timeout: float) -> bool:
    """True when the suite passes. A crash or a hang counts as a failure."""
    try:
        completed = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                *tests,
                # -x: a mutant is dead at the first failure, and the remaining
                # tests cost real seconds multiplied by the mutant count.
                "-x", "-q", "--no-header",
                "-p", "no:warnings", "-p", "no:cacheprovider",
            ],
            cwd=workspace,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0


# ---------------------------------------------------------------------------
# Verifying the mapping
# ---------------------------------------------------------------------------
#
# A target's test list is a claim about where a module's coverage comes from,
# and until now nothing checked it. It was wrong for five of the fourteen: the
# GSTR-1 section assembly in `filing` is only ever run by writing a return and
# reading it back, which `test_filing.py` does not do, so a seventh of that
# module was mutated against tests that never called it. Every mutant there
# survived, and the score read 68.8% — as if the assertions were missing, when
# in fact the caller was.
#
# A line the listed tests never execute can only produce survivors, so the
# cheap check is coverage, not mutation: one pytest run per target instead of
# one per mutant. It is on demand rather than in CI for the same reason the
# mutation run is — it costs a suite run per target — but it is what these
# lists are maintained with.


def _uncovered(payload: dict, module: str) -> list[int]:
    """Lines of *module* that the coverage *payload* records as never run."""
    files = payload.get("files", {})
    key = next((k for k in files if k.replace("\\", "/").endswith(module)), None)
    if key is None:
        raise RuntimeError(f"{module} is absent from the coverage report")
    return sorted(files[key]["missing_lines"])


def verify_target(target: Target, *, timeout: float = 600.0, root: Path = BACKEND) -> list[int]:
    """Lines of *target*'s module that its own test files never reach."""
    with tempfile.TemporaryDirectory(prefix="gstbot-verify-") as tmp:
        report = Path(tmp) / "coverage.json"
        subprocess.run(
            [
                sys.executable, "-m", "pytest", *target.tests,
                "-q", "--no-header", "-p", "no:warnings", "-p", "no:cacheprovider",
                # --cov takes the package, not the file: pointing it at a path
                # measures nothing and reports "No data to report", which reads
                # like a clean result.
                "--cov=app", f"--cov-report=json:{report}", "--cov-fail-under=0",
            ],
            cwd=root,
            capture_output=True,
            timeout=timeout,
            check=False,
            # The suite's own conftest sets what it needs; an inherited
            # COVERAGE_FILE from an outer run would be written to instead.
            env={k: v for k, v in os.environ.items() if k != "COVERAGE_FILE"},
        )
        if not report.is_file():
            raise RuntimeError(f"{target.name}: the tests produced no coverage report")
        return _uncovered(json.loads(report.read_text()), target.module)


def run_target(
    target: Target,
    *,
    jobs: int = 4,
    timeout: float = 120.0,
    limit: int | None = None,
    progress=None,
) -> Report:
    """Mutate *target*'s module and report which mutants its tests kill."""
    module_path = BACKEND / target.module
    original = module_path.read_text()
    sites = mutations(original)
    if limit is not None:
        sites = sites[:limit]

    report = Report(target=target.name, module=target.module, tests=list(target.tests))

    with tempfile.TemporaryDirectory(prefix="gstbot-mutation-") as tmp:
        root = Path(tmp)
        workspaces = [_make_workspace(root / f"w{n}") for n in range(max(1, jobs))]

        # The round-trip check. Every workspace starts from the normalized
        # source, so a mutant differs from its baseline by the mutation alone.
        baseline = normalize(original)
        for workspace in workspaces:
            _write_module(workspace, target.module, baseline)
        if not _run_tests(workspaces[0], target.tests, timeout):
            raise RuntimeError(
                f"{target.name}: the tests do not pass against the unmutated module. "
                "Fix the suite (or the round-trip) before reading a mutation score."
            )

        available = threading.Semaphore(0)
        pool: list[Path] = []
        pool_lock = threading.Lock()
        for workspace in workspaces:
            pool.append(workspace)
            available.release()

        def evaluate(site: Mutation) -> MutantResult:
            available.acquire()
            with pool_lock:
                workspace = pool.pop()
            try:
                mutated, applied = apply(original, site.index)
                _write_module(workspace, target.module, mutated)
                try:
                    passed = _run_tests(workspace, target.tests, timeout)
                    status = SURVIVED if passed else KILLED
                finally:
                    _write_module(workspace, target.module, baseline)
            finally:
                with pool_lock:
                    pool.append(workspace)
                available.release()
            result = MutantResult(
                index=applied.index,
                lineno=applied.lineno,
                operator=applied.operator,
                before=applied.before,
                after=applied.after,
                status=status,
            )
            if progress is not None:
                progress(result)
            return result

        with ThreadPoolExecutor(max_workers=max(1, jobs)) as executor:
            report.results = list(executor.map(evaluate, sites))

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.mutation",
        description=(__doc__ or "").split("\n")[0],
    )
    parser.add_argument("--target", action="append", choices=sorted(TARGETS_BY_NAME))
    parser.add_argument("--all", action="store_true", help="every registered target")
    parser.add_argument("--module", help="an ad-hoc module path, with --tests")
    parser.add_argument("--tests", nargs="+", help="test files for --module")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--limit", type=int, help="only the first N mutants (for a smoke run)")
    parser.add_argument("--json", type=Path, help="write the full report here")
    parser.add_argument(
        "--verify-tests",
        action="store_true",
        help="report module lines the target's own tests never run, and stop",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="exit non-zero if any target scores below this percentage",
    )
    return parser.parse_args(argv)


def _selected(args: argparse.Namespace) -> list[Target]:
    if args.module:
        if not args.tests:
            raise SystemExit("--module requires --tests")
        return [Target(Path(args.module).stem, args.module, tuple(args.tests))]
    if args.all:
        return list(TARGETS)
    if args.target:
        return [TARGETS_BY_NAME[name] for name in args.target]
    raise SystemExit("choose --target, --all or --module")


def _verify(targets: list[Target], *, timeout: float) -> int:
    """Print each target's unreachable lines. Non-zero when any target has some.

    Non-zero because a gap here is not a finding about the code, the way a
    survivor is — it is the tool being pointed at the wrong tests, and the
    score it would go on to print would be wrong rather than low.
    """
    incomplete = 0
    for target in targets:
        missing = verify_target(target, timeout=timeout)
        listed = " ".join(target.tests)
        if not missing:
            print(f"{target.name}: {listed} run every line of {target.module}", flush=True)
            continue
        incomplete += 1
        print(
            f"{target.name}: {len(missing)} line(s) of {target.module} are never run "
            f"by {listed} — every mutant there survives for want of a caller",
            flush=True,
        )
        print(f"    {', '.join(str(line) for line in missing)}", flush=True)
    return 1 if incomplete else 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    targets = _selected(args)
    reports: list[Report] = []
    failed = False

    if args.verify_tests:
        return _verify(targets, timeout=max(args.timeout, 600.0))

    for target in targets:
        total = len(mutations((BACKEND / target.module).read_text()))
        if args.limit is not None:
            total = min(total, args.limit)
        print(f"\n{target.name}: {total} mutants against {' '.join(target.tests)}", flush=True)

        done = 0

        def progress(result: MutantResult, _total: int = total) -> None:
            nonlocal done
            done += 1
            print(
                f"\r  {done}/{_total} " + ("." if result.killed else "S"),
                end="",
                flush=True,
            )

        report = run_target(
            target,
            jobs=args.jobs,
            timeout=args.timeout,
            limit=args.limit,
            progress=progress,
        )
        reports.append(report)
        print(f"\r  {report.summary()}{' ' * 20}", flush=True)
        for survivor in report.survivors:
            print(
                f"    SURVIVED {target.module}:{survivor.lineno} "
                f"{survivor.operator} {survivor.before!r} -> {survivor.after!r}",
                flush=True,
            )
        if args.fail_under is not None and report.score * 100 < args.fail_under:
            failed = True

    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in reports], indent=2))

    print("\n" + "=" * 60)
    for report in reports:
        print(report.summary())

    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
