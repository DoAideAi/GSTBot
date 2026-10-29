# GSTIndia

GST compliance for Indian SMBs. Ingests invoices, reconciles them against
GSTR-2B, computes the ITC position, prepares GSTR-1/3B for filing, and warns
about deadlines before they cost a late fee.

FastAPI + React + PostgreSQL, with Celery on Redis for background work. Runs on
one small VPS.

- **What it is for** — [`FEATURE_DOC.md`](FEATURE_DOC.md), the product scope.
- **How to change it** — [`CLAUDE.md`](CLAUDE.md), the working agreement: the
  conventions that are not derivable from reading a single file, and that a
  change is most likely to violate by accident. Read it before the first commit.
- **How to ship it** — [`deploy/README.md`](deploy/README.md), the runbook for
  the Hetzner box.

## Running it locally

Docker is the short path. It brings up Postgres, Redis, the API, a worker, the
scheduler and the built frontend behind nginx:

```sh
cp .env.example .env          # optional; every value below has a dev default
docker compose up --build
open http://localhost:3000
```

The API runs its migrations on start, so there is no separate setup step.
`OPENROUTER_API_KEY` is the only value worth filling in — without it invoice
parsing falls back to regex extraction, which still works (see "Degrading"
below).

### Without Docker

Two processes, plus a Postgres and a Redis of your own.

```sh
# backend
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp ../.env.example ../.env    # DATABASE_URL and JWT_SECRET at minimum
.venv/bin/alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --reload      # :8000

# frontend, in another shell
cd frontend
npm install
npm run dev                                            # :5173, proxied to :8000
```

Celery is optional locally: `CELERY_ENABLED=false` parses uploads inline in the
request instead of on a worker. To run the real thing:

```sh
cd backend
.venv/bin/celery -A app.celery_app worker -l info
.venv/bin/celery -A app.celery_app beat -l info
```

`python3.12` is named rather than `python3` because it is the interpreter CI
runs on. `tesseract-ocr` on the host is the OCR fallback for photographed
invoices; without it those uploads fail rather than degrade.

## Tests

The backend virtualenv is `backend/.venv`. Use it explicitly — a system or
conda Python resolves different packages and `tests/test_requirements.py` fails
for reasons that have nothing to do with the change.

```sh
cd backend
.venv/bin/python -m pytest                      # fast: no coverage
.venv/bin/python -m pytest --cov=app --cov-report=term-missing
.venv/bin/python -m ruff check app tests tools  # what CI lints
.venv/bin/python -m tools.mutation --target gstin

cd frontend
npm test
npm run test:coverage
npm run lint
```

4,304 tests on the backend and 911 on the frontend, both green, in about a
minute between them.

The suite runs with **every external service unavailable** — in-memory SQLite,
an unreachable Redis, no OpenRouter key — because that is how the degraded paths
get exercised. `backend/tests/conftest.py` sets its own environment with
`os.environ.setdefault`; anything exported outside silently wins and changes
what is under test. Never export test environment variables in a CI step or a
shell wrapper.

Coverage gates (99% backend in `pyproject.toml`; frontend statements and lines
at 99 and branches at 99.5 in `frontend/vite.config.js`) are ratchets against
tests being deleted or a module landing with none — not targets to code towards.

### The tests that fail when a new route or a new screen forgets something

Most files here test one unit. A handful sweep the assembled application
instead, and they are the ones most likely to go red on a change that looks
unrelated — which is the point of them. Adding a route or a page means adding
its entry, or explaining in the allowlist why it does not need one.

| Sweep | What it refuses to let through |
|---|---|
| `test_tenancy_contract.py` | A route with an `*_id` that another tenant can fetch |
| `test_request_guards.py` | A route reachable without resolving a user or a business |
| `test_rbac.py` | A mutating route without `require_writer`, and a gate that does not actually refuse a viewer |
| `test_openapi_contract.py` | A published spec that no longer matches the route's dependencies |
| `test_error_prose.py` | A refusal whose message names a Python type, an index, or a library |
| `frontend/src/App.loading.test.jsx` | A screen with no labelled placeholder while it waits |

Three more walk the product rather than its surface, over a fake API that keeps
state between requests, so a value one step produced is what the next step
reads: `backend/tests/test_end_to_end.py`,
`backend/tests/test_filing_journeys.py`, and `frontend/src/App.lifecycle.test.jsx`
(upload → parse → reconcile → file) with `App.rbac.test.jsx` beside it for what
a read-only session can and cannot do.

## Layout

```
backend/app/
  routers/    HTTP surface. Thin: parse, delegate to a service, serialize.
  services/   The domain. Where the GST rules actually live.
  schemas/    Pydantic request/response models. Validation belongs here.
  models/     SQLAlchemy ORM.
  core/       config, database, security, deps, rate_limit, middleware, errors.
  tasks/      Celery tasks (invoice parsing, alert digests, subscriber reminders, sweeps).
backend/tests/    One file per unit, plus route-table sweeps.
backend/tools/    mutation.py — a targeted mutation tester. Not deployed.
frontend/src/     pages/, components/, hooks/, lib/. Tests sit next to sources.
deploy/           systemd units, Caddy config, deploy.sh for the Hetzner box.
```

## The API

101 routes under `/api/v1`. The generated reference is the authority — start the
API and read it:

| | |
|---|---|
| Swagger UI | <http://localhost:8000/docs> |
| ReDoc | <http://localhost:8000/redoc> |
| Schema | <http://localhost:8000/openapi.json> |

What a route can answer is *derived* rather than declared: `core/openapi.py`
documents 401 only for routes that actually depend on `get_current_user` or
`get_current_business`, and 429 only for routes something actually counts.
`tests/test_openapi_contract.py` sweeps that the published spec still matches, so
a new route earns a correct spec by having correct dependencies.

The surface, by area:

| Area | Routes | What it does |
|---|---|---|
| `auth` | 14 | Register with a GSTIN, log in, sign out (revokes the token), change the password (ends older sessions), reset a forgotten one by emailed link, `/auth/me`; Google, GitHub and Microsoft sign-in (start and callback each), and which of them are configured |
| `businesses` | 6 | List linked registrations, link one, unlink, see and revoke links into this business, export its data |
| `invoices` | 7 | Upload (single and bulk), list, read, edit, re-extract, delete |
| `reconciliation` | 10 | Import GSTR-2B, run a match, read a run or the run history; buy and download a run's PDF report |
| `itc` | 4 | Eligible credit, Rule 37 reversals, lapsing credit, set-off |
| `filing` | 8 | GSTR-1/3B preparation, validation, late fee, export, record filed, undo a recorded filing |
| `suppliers` | 3 | Compliance scores, rescore |
| `alerts` | 3 | Deadline alerts, mark read, dismiss |
| `dashboard` | 1 | The monthly summary |
| `subscriptions` | 7 | Plans and prices, current plan, usage, Razorpay order and verify, cancel, webhook |
| `referrals` | 4 | Referral code, stats, leaderboard, tracking a visit |
| `meta` | 6 | State codes, GSTIN lookup, bulk GSTIN validation (paid), recent lookups, stats, deadline-reminder sign-up |
| `subscribers` | 3 | Newsletter sign-up, and unsubscribe by link or one-click POST |
| `feedback` | 6 | Send feedback, report a browser error; admin inbox and error log, and deleting from each |
| `advisor` | 2 | The GST AI advisor, answered whole or streamed |
| `gpt` | 7 | GPT Actions for ChatGPT: GSTIN, HSN, calculator, invoice data, filing dates, spec, privacy |
| `whatsapp` | 2 | The WhatsApp bot's webhook and its verification handshake |
| `seo` | 3 | `robots.txt`, the sitemap, share images |
| `health` | 5 | `live`, `ready`, `/health`, `/health/jobs`; request metrics per hour (admins only) |

Every response — a 404 from a route, a 422 from validation, a constraint
violation from Postgres, or a bug — has one shape:

```json
{
  "detail": "Invoice not found",
  "error": { "code": "not_found", "status": 404, "message": "Invoice not found" },
  "correlation_id": "9f2c1a0b4e7d5a63"
}
```

`detail` is what to show a person; `error.code` is what to branch on. A 500
never carries the exception — only the correlation id to quote. See
`backend/app/core/errors.py`.

### ChatGPT Custom GPT (GPT Actions)

The free tools are also published for ChatGPT under `/api/v1/gpt` — public,
stateless, rate-limited by address. To build a GPT on them, import
`https://gst.doaide.com/api/v1/gpt/openapi.yaml` as an Action (no auth), link
`https://gst.doaide.com/api/v1/gpt/privacy` as the privacy policy, and paste
the prompt from [`backend/app/gpt/gpt_instructions.md`](backend/app/gpt/gpt_instructions.md).
Scope and design: [`FEATURE_GPT_ACTIONS.md`](FEATURE_GPT_ACTIONS.md).

## Things worth knowing before changing anything

These are the four that catch people out. `CLAUDE.md` has the rest, with the
reasoning.

**Tenancy is not per-router.** Every business-scoped route resolves its tenant
through `get_current_business` in `app/core/deps.py` and nowhere else. A
cross-tenant read answers **404, never 403** — a 403 confirms the id exists, and
ids are sequential. Four sweeps over the assembled route table enforce this
rather than trusting habit, and they are the tests most likely to fail on a new
endpoint: add a route, add a factory in `tests/test_tenancy_contract.py`, or the
file fails.

**Roles enforce exactly one line: a viewer may not write.** `owner` >
`accountant` > `viewer`, with `Depends(require_writer)` on every mutating route
and `tests/test_rbac.py` sweeping that nothing new ships without it. A role
refusal is a **403**, not the tenancy 404 — the caller is a member and knows the
business exists. Owner and accountant are deliberately not separated: an outside
CA doing a client's GST work needs every write this API has.

**Degrading is the design, not a fallback.** OpenRouter absent or rate-limited →
the parser uses regex/heuristic extraction. Redis down → rate limiting counts
in-process and uploads parse inline. SMTP failing for one tenant must not end
the digest for the rest. `localStorage` blocked → the session lives in memory for
the tab. When adding a dependency, decide the degraded path first and test it.

**Money is `Decimal`, never float.** GSTINs are validated through
`services/gstin.py` (15 characters with a check digit), never a bare regex. Tax
splits are IGST inter-state and CGST+SGST intra-state, decided by comparing the
supplier's and buyer's state codes — not by trusting the invoice.

## Formatting

**Do not run a formatter over this repository.** Both halves are hand-formatted
so comment blocks and long call signatures stay readable, and CI deliberately
checks correctness only:

- Backend: `ruff check`, never `ruff format` — the formatter disagrees with
  roughly every file. There is a comment saying so in `.github/workflows/ci.yml`.
- Frontend: `eslint` only. Prettier is not a dependency and there is no config
  for it; running one anyway rewrites 47 of 57 files, and no `printWidth`
  narrows that below 35. The disagreement is deliberate, the same as the
  backend's.

## Migrations

A model change needs an Alembic revision in the same commit. CI runs `alembic
check` against a real Postgres and fails when the migrations no longer produce
the schema the models expect. `tests/test_migrations.py` additionally asserts
that going back one revision reproduces the schema that revision's release ran
on — run twice, once on SQLite and once on Postgres, because `batch_alter_table`
is exactly where the two backends diverge.

Deletes are soft, via `deleted_at` (`models/mixins.py`). Partial unique indexes
are predicated on `deleted_at IS NULL`. Filter it in queries.

## Committing

Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`). Run
`ruff check` and both suites before pushing — CI lints with an unpinned ruff, so
a new release can turn `main` red with no code change.
