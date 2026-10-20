# GPT Actions — DoAide GST tools inside ChatGPT

## What

A public, unauthenticated API surface at `/api/v1/gpt/*` that exposes the
product's free GST tools in a shape an OpenAI Custom GPT can call as
**Actions**, plus everything a person needs to wire one up:

| File / route | Purpose |
| --- | --- |
| `backend/app/gpt/openapi.yaml` | OpenAPI 3.1 spec for the Actions — paste into the GPT builder, or import from the URL below. Lives inside `app/` so every deployment (including the Docker image, whose context is `backend/`) can serve it. |
| `GET /api/v1/gpt/openapi.yaml` | The same spec, served, so the builder can "Import from URL". |
| `GET /api/v1/gpt/privacy` | Privacy statement — a public GPT with Actions must link one. |
| `backend/app/gpt/gpt_instructions.md` | GPT builder settings plus the instruction prompt to paste into the GPT's *Instructions* box. |

## Endpoints

All `GET` except invoice generation, all free, no auth, rate-limited by IP.
Every one is a thin wrapper over a service the web tools already use — no GST
rule is re-implemented for the GPT.

| Operation | Route | Backed by |
| --- | --- | --- |
| `validateGstin` | `GET /gpt/gstin/{gstin}` | `services/gstin.py` — format, check digit, state, PAN, entity type |
| `searchHsn` | `GET /gpt/hsn?q=` | `services/hsn.py` — the HSN/SAC table the `/hsn` page ships, exported to `hsn_data.json`; a test fails if the two drift |
| `calculateGst` | `GET /gpt/calculate` | `services/gst_calculator.py` — exclusive/inclusive, CGST+SGST vs IGST by state codes |
| `generateInvoice` | `POST /gpt/invoice` | `services/gst_calculator.py` — line totals, tax split, amount in words; **returns JSON, not a PDF** |
| `getFilingDates` | `GET /gpt/filing-dates` | `services/gst_calendar.py` + `services/late_fee.py` — GSTR-1/3B/IFF/CMP-08/GSTR-9 dates, days left, late fee so far |

Design points:

- **Nothing is written.** No route reads or writes a tenant row; the invoice
  endpoint computes and returns. That is why `POST /gpt/invoice` is on the
  `require_writer` exemption list next to `/itc/set-off`.
- **Money stays `Decimal`** and is serialised as strings, as everywhere else.
- **Tax split by state code, not by trust**: supplier/buyer state come from
  their GSTINs when given, else from explicit state codes.
- **Errors are answers.** An invalid GSTIN is `200 {"valid": false}` (the GPT
  explains it to the user); malformed input is a 422 with the usual error shape.
- **Bounded inputs** — every string has a length or pattern, every Decimal a
  floor and ceiling, periods use `PERIOD_PATTERN` — so the route-contract
  sweeps pass without exemptions.

## CORS

GPT Actions are called server-side from OpenAI, so CORS is not strictly
required, but the builder's "Test" panel and future browser clients run from
OpenAI origins. A small pure-ASGI middleware answers preflights and decorates responses
for `/api/v1/gpt/*` only, for `https://chat.openai.com`, `https://chatgpt.com`
and `https://platform.openai.com` — without credentials. The app-wide CORS
policy (credentialed, SPA origins only) is unchanged.

## Rate limiting

ChatGPT calls arrive from OpenAI's egress addresses, so many users share a few
IPs. The GPT bucket (`gpt_actions`) is therefore generous (600/minute per IP)
and, like every bucket, retunable through `RATE_LIMIT_OVERRIDES` without a
deploy. The global per-IP limit (`RATE_LIMIT_DEFAULT`, 300/minute) still
applies underneath; raise `global` if GPT traffic meets it.

## Tests

`backend/tests/test_gpt_actions.py` — every endpoint's happy path and its
refusals, the CORS behaviour for OpenAI vs. other origins, and that the
served spec matches the routes the app actually mounts. The public-route
allowlists in `test_request_guards.py`, `test_rbac.py` and
`test_openapi_contract.py` are extended deliberately.

## Out of scope

Live GSTIN status from the GST portal (needs a GSP licence), PDF rendering,
any authenticated (tenant) data through the GPT.
