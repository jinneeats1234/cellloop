# CellLoop architecture

This document explains how CellLoop is put together and the conventions the code follows.
For setup and day-to-day use, see the [README](../README.md); for AWS, see
[deployment-aws.md](deployment-aws.md).

## System overview

```
                         ┌──────────────────────────── AWS account ────────────────────────────┐
 Partner lab ─┐          │                                                                      │
 Scientist  ──┼─► React SPA ──HTTPS──► FastAPI ──► RDS PostgreSQL + pgvector                    │
 Leadership ──┘   (Vite, Tailwind,      │  │         experiments · chunks (HNSW) · audit_log    │
                   Plotly)              │  ├──────► S3 (SSE-KMS): raw partner files            │
                     │                  │  ├──────► Bedrock · Claude: extraction, cited Q&A     │
                     └── Cognito (PKCE) │  └──────► Bedrock · Titan v2: embeddings             │
                                        └── NumPy/SciPy or BoTorch GP: next-experiment ranking  │
                         └──────────────────────────────────────────────────────────────────────┘
```

### The three AI jobs

| Job | Where | Guardrails |
|---|---|---|
| **Report extraction**: messy PDFs, spreadsheets and impedance exports → structured records | `services/parsing.py` → `services/extraction.py` → `services/llm.py` | Claude structured output with a JSON schema generated from `experiment_schema.py`. Each value carries a verbatim evidence quote; quotes not found in the source are downgraded and flagged. Nothing is saved as a record until a scientist approves it. |
| **Next-experiment recommender**: most learning per expensive test | `services/recommender.py` | Classical ML, not an LLM: Gaussian process + Expected Improvement. Every suggestion shows a 95% interval, P(beats target), the nearest prior test and a rationale computed from the model. |
| **Cited Q&A**: "have we tried this before, and what happened?" | `services/rag.py` | Tenant-scoped retrieval over approved data only. Declines when no passage clears the similarity threshold, when the model reports insufficient evidence, or when the answer has no valid citation. |

### Data lifecycle

1. **Upload** (`POST /api/documents`): type and size checks, duplicate check (SHA-256), raw file stored, audit `upload`.
2. **Extraction** (background task): parse → Claude → validate types and ranges → verify evidence → derive ASR from EIS / I-V curves → draft `Experiment` rows (`pending_review`), audit `ai_extraction`.
3. **Review** (`/review/:id`): the scientist edits and approves or rejects. Approval records the AI-versus-final diff (audit `approve`) and indexes the record and its source for Q&A.
4. **Use**: approved records feed the registry, dashboard, recommender and Q&A.

## Repository layout

```
cellloop/
├── backend/
│   ├── app/
│   │   ├── main.py               App assembly: middleware, error handlers, routers, health check
│   │   ├── core/                 Infrastructure shared by every feature
│   │   │   ├── config.py           Settings from env/.env, validated at startup
│   │   │   ├── database.py         SQLAlchemy engine/session, schema creation
│   │   │   ├── security.py         Cognito / dev JWT verification, role dependencies
│   │   │   ├── access.py           Tenant scoping (the only place partner isolation lives)
│   │   │   ├── audit.py            Append-only audit log helpers
│   │   │   ├── errors.py           Error types, consistent JSON errors, handlers
│   │   │   └── logging.py          Request IDs, log format, access log
│   │   ├── experiment_schema.py  Single source of truth for the ~28 experiment fields
│   │   ├── models.py             ORM models
│   │   ├── serializers.py        ORM → JSON
│   │   ├── routers/              HTTP endpoints, thin: validate → call services → audit
│   │   ├── services/             Domain logic: parsing, extraction, llm, rag, recommender, impedance, storage
│   │   └── scripts/seed.py       Demo data (python -m app.scripts.seed)
│   ├── tests/                    pytest: access control, workflow, science, errors
│   ├── .env.example              Every backend setting, documented
│   └── requirements*.txt
├── frontend/
│   ├── src/
│   │   ├── main.tsx · App.tsx    Entry point and routes
│   │   ├── api/                  Typed API client (timeouts, ApiError) and response types
│   │   ├── auth/                 Auth context and Cognito PKCE flow
│   │   ├── config/env.ts         Typed access to VITE_* variables
│   │   ├── components/
│   │   │   ├── ui/                 Design-system primitives (Card, Badge, Icon, feedback…)
│   │   │   ├── charts/             Plotly wrapper and scientific charts
│   │   │   ├── layout/             App shell (sidebar, navigation)
│   │   │   └── ErrorBoundary.tsx   Crash recovery screen
│   │   ├── hooks/                useAsync
│   │   ├── lib/                  Pure helpers: validation rules, formatting
│   │   ├── pages/                One file per route
│   │   └── styles/index.css      Design tokens (light + dark) and component classes
│   └── .env.example
├── db/init.sql                   pgvector extension (Postgres / RDS)
├── docs/                         Architecture and AWS deployment
├── samples/                      Example partner report, EIS export, internal reports
├── docker-compose.yml            Postgres + API + web
└── start.sh                      One-command local start
```

**Conventions**

- **Routers stay thin.** They validate input, call a service, write the audit entry, and return. Logic that could be reused or tested lives in `services/`.
- **Tenant isolation lives in one place.** Every query for partner-owned data goes through `core/access.py` (`scope`, `get_scoped`). Out-of-scope IDs return 404 rather than 403, so IDs can't be probed.
- **One schema drives everything.** Adding a field to `experiment_schema.py` adds the DB column, the extraction schema, validation, completeness scoring and the review form.
- **Frontend imports go through barrels.** Pages import primitives from `components/ui` and helpers from `lib/`.

## Error handling

### API error contract

Every error response has the same shape, and every response carries an `X-Request-ID` header:

```json
{ "detail": "Experiment not found", "code": "not_found", "request_id": "9f2c1a7e3b4d5c6a" }
```

- `detail`: a user-safe message (or, for 422, the list of field errors plus a readable `message`).
- `code`: a stable identifier clients can branch on (`not_found`, `validation_error`, `ai_rate_limited`, `file_missing`, …).
- `request_id`: matches the server log line for the request. Users can quote it when reporting a problem.

### Layers

| Layer | What happens |
|---|---|
| **Configuration** (`core/config.py`) | Settings are type-checked and cross-checked at startup (for example, Cognito mode needs a pool ID, prod forbids dev auth and SQLite). Problems print as a readable list and the server exits with status 2. |
| **Startup** (`main.py`) | If the database can't be reached, the server logs a clear critical message and exits. |
| **Expected failures** (`core/errors.py`) | Services raise `NotFoundError`, `ConflictError`, `ProcessingError`, `UpstreamError` or `ServiceUnavailableError`, each with a user-safe message and a code. |
| **AI calls** (`services/llm.py: ai_errors`) | Anthropic SDK and Bedrock errors become retryable messages: throttling → 503 `ai_rate_limited`; unreachable → 502 `ai_unreachable`; bad credentials or model access → 502 `ai_misconfigured` (logged for admins). Refusals, truncation and malformed output are caught too. The SDK retries transient errors (`LLM_MAX_RETRIES`) with a timeout (`LLM_TIMEOUT_S`). |
| **Storage** (`services/storage.py`) | A missing file → 404 `file_missing`; disk or S3 failures → 502 with a retry hint. A failed upload write rolls back the database row. |
| **Background work** (extraction, indexing) | Failures mark the document `failed` with a user-safe message. The technical exception goes to the audit log and server logs. |
| **Recommender** | If BoTorch fails numerically, it falls back to the built-in GP. If both fail → 422 `model_fit_failed` with guidance. |
| **Database** | Connection loss → 503 `database_unavailable`; other SQL errors → 500 without internals. `/api/health` returns 503 when the DB is unreachable. |
| **Anything else** | Logged with a stack trace and request ID. The client gets a 500 with a reference ID and no internals. |
| **Frontend: API client** (`api/client.ts`) | Every failure becomes an `ApiError` with a readable message, `code`, `requestId` and `retryable`. Requests time out (30 s by default, 180 s for AI calls). Network failures and proxy 502s produce "can't reach the server" guidance. A 401 signs the user out. |
| **Frontend: UI** | `ErrorBanner` shows the message, the reference ID and a Retry button for transient failures. Forms validate inline before submitting (`lib/validation.ts`). `ErrorBoundary` catches rendering crashes per page (the sidebar stays usable) and at the root. Charts that fail to draw show an inline note. Unknown routes show a 404 page. If the API is down at startup, the app shows "Can't reach the CellLoop API". |

## Security and responsible AI

- **Partner isolation** is enforced in SQL for every partner-owned table and in retrieval. Partner uploads are forced into the partner's own organization. `tests/test_access.py` covers it.
- **Prompt-injection hygiene.** Documents and retrieved passages are wrapped as untrusted data, and the system prompts tell Claude to ignore instructions inside them. Claude has no tools, so a hostile document can at most produce a draft that a human must approve.
- **Auditing.** Uploads, downloads, AI extractions, edits, approvals with AI-versus-final diffs, rejections, questions and recommendation runs are all logged.
- **Data residency.** In production, Claude and the embeddings run through Amazon Bedrock in the company's AWS account, and inputs are not used for model training.
