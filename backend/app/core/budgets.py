"""How long each route is allowed to take, and which ones are missing it.

One flat threshold — ``metrics.SLOW_MS``, a second — said a 900 ms dashboard
was fine and a 1.1 s reconciliation was slow, which is close to backwards: the
dashboard is a handful of indexed reads a person is waiting on, and the run
walks a month of purchases against a statement. A budget is per route, set
from what the route does, so "over budget" means "slower than this route
should be" rather than "slower than some other route would be".

Keyed by the route template the router matched (``/invoices/{invoice_id}``,
without the API prefix), so every id shares one budget. Anything not listed
falls back on its method: a read is a person waiting on a screen, a write
does slightly more and is waited on less often.
"""
from __future__ import annotations

READ_MS = 500
WRITE_MS = 1000

# Only the routes that are slow by nature. A route that is listed here to
# excuse slowness it should not have is the thing this table exists to catch,
# so each entry says what makes the time legitimate.
ROUTE_BUDGETS_MS: dict[tuple[str, str], int] = {
    # bcrypt is deliberately slow, and sign-in hashes once.
    ("POST", "/auth/login"): 1500,
    ("POST", "/auth/register"): 1500,
    # Stores the file and queues the parse; inline parsing only happens when
    # Celery is off, and then the model's own budget is the honest limit.
    ("POST", "/invoices/upload"): 5000,
    ("POST", "/invoices/bulk"): 15000,
    ("POST", "/invoices/{invoice_id}/reparse"): 5000,
    # A month's GSTR-2B parsed and stored; a month's purchases matched.
    ("POST", "/reconciliation/gstr2b/import"): 5000,
    ("POST", "/reconciliation/run"): 5000,
    # A PDF rendered on request.
    ("GET", "/reconciliation/{run_id}/report.pdf"): 3000,
    # One upstream model call, bounded by its own 20 s timeout.
    ("POST", "/advisor/ask"): 20000,
    # A period's returns assembled from every invoice in it.
    ("GET", "/filing/gstr1"): 2000,
    ("GET", "/filing/gstr3b"): 2000,
    ("GET", "/filing/export/{return_type}.{extension}"): 3000,
    # Up to a hundred checksums and a pipelined Redis write.
    ("POST", "/meta/gstin/bulk"): 2000,
}

_READS = frozenset({"GET", "HEAD", "OPTIONS"})


def budget_for(method: str, route: str | None) -> int:
    """The time *route* is allowed, in milliseconds."""
    if route is not None:
        listed = ROUTE_BUDGETS_MS.get((method, route))
        if listed is not None:
            return listed
    return READ_MS if method in _READS else WRITE_MS
