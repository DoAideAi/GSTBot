# GSTIndia

AI GST compliance for Indian SMBs: invoice ingestion, GSTR-2B reconciliation, ITC
calculation, filing preparation, and deadline alerting. FastAPI + React +
PostgreSQL, with Celery on Redis for background work.

`FEATURE_DOC.md` is the product scope. This file is the working agreement — the
conventions that are not derivable from reading a single file, and that a change
is most likely to violate by accident.

## Layout

```
backend/app/
  routers/    HTTP surface. Thin: parse, delegate to a service, serialize.
  services/   The domain. Where the GST rules actually live.
  schemas/    Pydantic request/response models. Validation belongs here.
  models/     SQLAlchemy ORM.
  core/       config, database, security, deps, rate_limit, middleware, errors.
  tasks/      Celery tasks (invoice parsing, alert digests, sweeps).
backend/tests/    One file per unit, plus route-table sweeps (see below).
backend/tools/    mutation.py — a targeted mutation tester. Not deployed.
frontend/src/     pages/, components/, hooks/, lib/. Tests sit next to sources.
deploy/           systemd units, Caddy config, deploy.sh for the Hetzner box.
```

## Commands

The backend virtualenv is `backend/.venv`. Use it explicitly — a system or
conda Python resolves different packages and `tests/test_requirements.py` fails
for reasons that have nothing to do with the change.

```bash
cd backend
.venv/bin/python -m pytest                      # fast: no coverage
.venv/bin/python -m pytest --cov=app --cov-report=term-missing
.venv/bin/python -m ruff check app tests tools  # what CI lints
.venv/bin/python -m tools.mutation --target gstin
.venv/bin/python -m tools.mutation --all --verify-tests   # before reading a score
.venv/bin/python -m uvicorn app.main:app --reload

cd frontend
npm test
npm run test:coverage
npm run lint
```

`docker compose up` brings up Postgres, Redis, the API, a worker and beat. The
backend image's entrypoint takes `api`, `worker`, or `beat`.

## Conventions that bite

**Never run `ruff format`.** It would reformat ~122 of 130 files. The source is
hand-formatted so comment blocks and long call signatures stay readable, and CI
deliberately runs only `ruff check` — see the comment in `.github/workflows/ci.yml`.
Lint enforces correctness; layout is left alone.

**Never export test environment variables** in CI steps or shell wrappers.
`backend/tests/conftest.py` sets its own with `os.environ.setdefault`, pointing at
in-memory SQLite, an unreachable Redis, and no OpenRouter key — so the degraded
paths are what the suite actually exercises. Anything exported outside silently
wins and changes what is under test.

**Coverage gates are ratchets, not targets.** 99% backend (`pyproject.toml`);
frontend statements and lines at 99, functions at 99 and branches at 99.5
(`frontend/scripts/coverage-thresholds.mjs`, read by `vite.config.js`).
Branches sits below the measured figure because three guards are unreachable by
construction — the comment above `thresholds` in `vite.config.js` says which.
CI checks them in a "Coverage threshold" step after Test, so a red Test step
means a test failed, never just a gate. They exist so that
deleting tests or landing a module with none fails CI. Raise a gate in the
commit that earns it; never write a test purely to move the number.

**A mutation target's test list is a claim, and it has been wrong.** Each entry
in `tools/mutation.py` names the files that cover its module, and a line those
files never *run* produces survivors that look exactly like missing assertions.
Five of the thirteen were short — `filing` scored 68.8% against `test_filing.py`
alone while a seventh of the module is only reached by writing a return and
reading it back in `test_filing_record.py`. Run `--verify-tests` before reading
a score, and when you add a test file that reaches a target module by a path no
listed file takes, add it to the target.

**A survivor that is not a missing assertion is recorded where it lives.** Some
mutants no test can kill — an edge the guard above it has already returned on, a
rounding whose every value is exact, a cap the pattern feeding it cannot reach.
Left unexplained, each one is re-investigated on every run. The convention is a
comment at the line saying which mutant survives and what makes the two readings
indistinguishable, so a *new* survivor is the thing that stands out. Prove the
claim by running it, not by reading: `reconciliation` and `supplier_score` sit
at 96.5% and 97.4% with every remaining survivor equivalent, and `invoice_parser`
at 96.8% for the same reason — those are ceilings, not gaps.

**Comments explain why, not what.** This codebase's comments carry the reasoning
that would otherwise be lost — why a 200 and not a 503, why this window and not
that one, why the obvious alternative was rejected. Match that. A comment
restating the line below it is noise here.

**Tests are named as claims.** `test_a_payment_before_the_invoice_was_issued_is_refused`,
not `test_payment_validation`. The name is what broke when it goes red.

## Tenancy

Multi-tenant by `business_id`. Every business-scoped route resolves its tenant
through `get_current_business` in `app/core/deps.py` and nowhere else — a route
that reads `current_user.business_id` itself has no single place left to audit.
`X-Business-Id` naming a different business is honoured only against a live
`BusinessMembership`; anything else is 403.

Cross-tenant reads answer **404, never 403**. A 403 confirms the id exists, and
ids are sequential, so a competitor's invoice count is a loop away.

Four sweeps over the assembled route table enforce this rather than trusting
per-router habit, and they are the tests most likely to fail on a new endpoint:

- `tests/test_tenancy_contract.py` — any route with an `*_id` path parameter
  must appear in `FACTORIES` with a way to build a row for one tenant. It is
  then fetched by the *other* tenant and required to 404. Add a route, add a
  factory, or the file fails.
- `tests/test_request_guards.py` — every route not on an explicit public
  allowlist must depend on `get_current_user` or `get_current_business`.
- `tests/test_rbac.py` — every route with a mutating method, outside an
  explicit list, must depend on `require_writer`. See Roles below.
- `tests/test_route_contracts.py` — shared route inventory the other three read.

The public allowlist is deliberate and short: the three health probes,
`/health/jobs`, the two `/meta/*` lookups, and login/register. Adding to it is a
security decision, not a convenience.

## Roles

`owner` > `accountant` > `viewer`, and only one line between them is enforced:
a viewer may not write. `Depends(require_writer)` on every mutating route says
so, and `tests/test_rbac.py` sweeps that nothing new ships without it.

The role is resolved with the tenant, in `get_active_tenant`, and for the same
reason tenancy is: the answer depends on *which business the request acts for*.
A login acting as itself carries `User.role`; one acting for a linked business
through `X-Business-Id` carries that `BusinessMembership.role` instead. Reading
`current_user.role` in a handler would give an owner of their own books an
owner's authority over every client they have been linked into. `require_writer`
and `get_current_business` share one dependency, so the membership is still read
once per request.

Role refusals are **403, not the tenancy 404**. The caller is a member of this
business and knows it exists, and the answer does not depend on the id in the
path — a viewer gets the same 403 for a real row, another tenant's row, and one
that has never existed — so it confirms nothing a 404 would hide. The detail
names the role held and who to ask, because that is the only thing the reader
can act on.

Owner and accountant are deliberately not separated. An outside CA doing a
client's GST work needs every write this API has, and a product that refused
them one would be routed around by sharing the owner's password.

## Rate limiting

`RateLimit("name", "60/minute", by="ip"|"identity")` as a route dependency. The
name is the bucket key and is overridable per environment through
`RATE_LIMIT_OVERRIDES`, so an operator can retune during an incident without a
deploy. Counters live in Redis and fall back in-process when it is unreachable;
a dead Redis must never fail the request it is limiting.

Public endpoints are keyed by IP — there is no identity before sign-in.
`/health` and `/health/jobs` are metered because they cost real work per call (a
database round-trip, a fresh Redis connection, and a Celery ping that holds the
thread up to a second).

There are two layers, and a route can be exempt from one without the other. The
per-route buckets above are dependencies; underneath them
`RateLimitMiddleware` counts *every* path outside `_UNLIMITED_PATHS`, which
today is `/health/live` alone. It is unbounded because it touches no dependency
— an unlimited flood of it costs one dict, while metering it would eventually
have an orchestrator kill a pod for being healthy. `/metrics` was in that set
too and no route has ever answered it; the limiter matches before the router
does, so it was an uncounted path with nothing behind it. Adding to this set is
a decision about what a path costs to serve, and
`tests/test_request_guards.py::test_nothing_is_exempted_from_counting_that_is_not_a_route`
now requires that the path exists before the decision can be made about it.

`/health/ready` carries no bucket of its own but is still counted globally, and
that is deliberate rather than an oversight: it runs the same `SELECT 1` on the
pooled connection that `/health` does, so exempting it would leave an
unauthenticated route that can be hammered without bound into the pool every
tenant is served from. At the default 300/minute per address a load balancer
probing every five seconds spends twelve, so real probes never meet it. See
`_UNLIMITED_PATHS` in `core/middleware.py` and
`tests/test_request_guards.py::TestTheHealthProbesAndTheGlobalLimit`.

What a route can answer is derived from these two facts rather than declared:
`core/openapi.py` documents 401 only for routes that actually depend on
`get_current_user`/`get_current_business`, and 429 only for routes something
actually counts. `tests/test_openapi_contract.py` sweeps that the published
spec still matches. A new route earns a correct spec by having correct
dependencies.

## Database and migrations

Model changes need an Alembic revision in the same commit. CI runs `alembic
check` against a real Postgres and fails when the migrations no longer produce
the schema the models expect — a column added without one surfaces there rather
than as an `UndefinedColumn` in production.

`tests/test_migrations.py` asserts that going back one revision reproduces the
schema that revision's release ran on. CI runs it twice: once on SQLite in the
suite, once against Postgres, because `batch_alter_table` is exactly where the
two backends diverge.

Soft deletes via `deleted_at` (see `models/mixins.py`); partial unique indexes
are predicated on `deleted_at IS NULL`. Filter it in queries.

## External services degrade, never fail

OpenRouter absent or rate-limited → `invoice_parser` falls back to regex/heuristic
extraction. Redis down → rate limiting counts in-process, uploads parse inline.
SMTP failing for one tenant must not end the digest for the rest. When adding a
dependency, decide the degraded path first and test it — the suite runs with all
of them unavailable, so a new hard dependency shows up as a broad failure.

## Money and GST specifics

`Decimal` throughout, never float. GSTINs are 15 characters with a check digit —
validate through `services/gstin.py`, never a bare regex. Tax splits are
IGST for inter-state, CGST+SGST for intra-state, decided by comparing the
supplier's and buyer's state codes, not by trusting the invoice.

## Committing

Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`). Run
`ruff check` and both suites before pushing — CI runs the same pinned ruff and pytest
(`backend/requirements-dev.txt`), so what passes here passes there.
