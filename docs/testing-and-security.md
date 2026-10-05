# CellLoop: test inventory, results and security audit

**Date:** 4 October 2026 · **Scope:** the CellLoop application in this repository (backend API, React frontend,
configuration, Docker setup) · **Result:** 52/52 browser test steps and 115/115 automated backend tests pass.
9 vulnerabilities and robustness bugs were found and fixed. No secrets are exposed, and there is no SQL
injection path.

## 1. Feature and control inventory

Every page, button, form field and link. Roles: **S** scientist, **L** leadership, **A** admin, **P** partner.

| Page | Roles | Controls tested |
|---|---|---|
| Login | all | 6 demo-account buttons (dev); "Continue with your organization account" (Cognito mode) |
| Sidebar | all | Every nav link for the role; Sign out (desktop and phone header) |
| Dashboard | S L A | "Show table" / "Show chart" toggle; "Open review queue" link; experiment links in the table; 3 charts (hover) |
| Experiments (registry) | all | Search box; Status select (All / Approved / Pending / Rejected); Operating temp ±25 °C; Search button; record links (table on desktop, cards on phone) |
| Experiment detail | all | "Review this record" (S A, pending only); Nyquist and polarization charts; "Back to experiments" on not-found |
| Review queue | S A | "Review" button per record (table and card layouts) |
| Review (record) | S A | ~28 field inputs; field focus → evidence highlight; Original / Extracted text switch; jump-to-field links in the error summary; "I've checked these values" checkbox; review comment; Approve record; Save draft; reject reason + Reject; Back to queue |
| Next experiment | S L A | Suggestions, operating temp, target ASR, cathode filter; Recommend experiments; best-so-far and nearest-test links |
| Ask the program | S L A | Question box; Ask; 4 example-question buttons; citation superscripts; citation record links |
| Upload report | P S A | File picker / drag-and-drop; Title; Document type and Partner selects (internal users); Upload; "View all submissions" |
| Submissions | P S A | Refresh; Upload report; record links |
| Audit log | S L A | Action filter (11 options); Show / Hide details per entry |
| Errors | all | 404 page ("Back to start"); not-found record; "Can't reach the API" screen (Try again); crash screen (Reload page / Go to start); Retry on error banners |

## 2. Browser testing

A scripted, real-browser click-through (headless Chrome) ran against the **production build**, with the
production Content-Security-Policy enforced. It covered three screen widths (1440 px desktop, 768 px tablet,
390 px phone) and all three roles. Each step also checked for JavaScript errors, console errors, CSP
violations, error-boundary crashes, horizontal overflow, and whether an XSS payload had executed.

| Area | Normal inputs | Weird / hostile inputs | Result |
|---|---|---|---|
| Sign in / out, navigation | Each role; every nav link | Partner opens `/dashboard`; leadership opens `/upload` | Pass: "Page not found" |
| Registry search | `LSCF` (19 records) | `' OR 1=1 --`, `<img onerror>`, `%`, emoji + `µm Ω·cm²`, 250 chars, whitespace; temp `abc` | Pass: no leaks; `%` literal; `abc` blocked inline |
| Recommender | Default run (5 suggestions) | n = `0`, `abc`, `1e309`; temp `-5`, `Infinity`; target `0`; 150-char filter; XSS filter | Pass: all 7 blocked inline; hostile filter → safe empty result |
| Ask | Example questions; citation links | Empty, `hi`, 2001 chars, XSS, SQL text, prompt-injection text | Pass: validated; declines or answers with citations only |
| Upload | Valid report → extracted → review queue | No file, `.exe`, empty file, 26 MB file, 520-char title, HTML disguised as `.pdf` | Pass: rejected with clear messages (fake PDF rejected by the server) |
| Review | Edit, Save draft, Approve | OCV `abc`, `1e309`, `3` V; cycles `2.5`; invalid date; HTML in notes; whitespace reject reason | Pass: errors block approval; implausible values need the checkbox |
| Stored XSS | — | Report whose lab, cathode and notes hold `<img onerror>`, `<script>`, `javascript:` | Pass: shown as text on review, registry, detail, dashboard charts and Q&A |
| Audit, Submissions | All 11 filters; Show/Hide; Refresh | — | Pass |
| Error states | — | Unknown route; missing record; API stopped | Pass: friendly screens, reference IDs |

**Totals:** 52/52 steps passed, with 0 console errors, 0 CSP violations, 0 crashes, 0 overflow and 0 executed payloads.

## 3. Automated backend tests

`cd backend && .venv/bin/python -m pytest` runs **115 tests**:

- **Access control:** partner isolation for every endpoint; role checks.
- **Workflow:** upload → extraction → review → approve → Q&A.
- **Science:** impedance analysis, GP model.
- **Errors:** error shape, request IDs, hidden internals, health check, AI outage, corrupt files, bad configuration.
- **Security (`tests/test_security.py`, 82 cases):**
  - SQL-injection strings in every search and filter;
  - path traversal, tenant spoofing and weird filenames;
  - content-type spoofing;
  - NaN, Infinity and 10³⁰ values; NUL bytes; whitespace-only text;
  - malformed query parameters and tampered or expired JWTs (including `alg: none`);
  - security headers, oversized uploads and rate limiting.

## 4. Security audit

### Vulnerabilities and bugs found and fixed

| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | **High** | **Stored XSS via downloads.** The uploader's Content-Type was stored and replayed, so a partner could upload HTML labelled `text/html` and have it served as a page. | The file type is decided by the server from the extension, and PDF/XLSX must match their header bytes. Every download is an attachment with `nosniff` and a sandbox CSP. |
| 2 | **High** | **Path traversal.** An internal user's `organization` form value became part of the storage path (`../../etc` → 500, write attempted outside the storage root). | The organization must be an existing partner organization. The storage layer also rejects any path outside its root. |
| 3 | Medium | **Non-finite and absurd numbers** (NaN, Infinity, 1e309, 10³⁰) were accepted as measurements. Some crashed the API (invalid JSON or integer overflow). | Rejected by the backend and the forms; magnitudes over 10⁹ are refused. |
| 4 | Medium | **No rate limiting** on AI calls, uploads or dev sign-in (cost and denial-of-service risk). | Per-user limits: 20 AI calls, 30 uploads and 20 dev sign-ins per minute, with 429 + `Retry-After`. |
| 5 | Medium | **Missing security headers.** API responses could be cached and framed. | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on the API, HSTS in prod. A CSP for the web app (nginx and preview). |
| 6 | Low | **Internal staff emails** were visible to partners (reviewer, and uploader for on-behalf uploads). | Shown to partners as "CellLoop team". |
| 7 | Low | **LIKE wildcards:** `%` and `_` in a search matched everything. Not an injection, but a correctness and enumeration issue. | Escaped, so they match literally. |
| 8 | Low | **Unvalidated input:** NUL bytes and whitespace-only questions or reasons were accepted; negative `limit`/`offset` and non-numeric `/similar` parameters caused 500s. | Shared text rules (strip, reject NUL, length checked after trimming); typed query parameters return 422. |
| 9 | Low | **Hardening:** token errors echoed library messages; API docs were exposed in prod; the Docker DB password was hard-coded and ports were bound to all interfaces; chart labels could render partner-supplied HTML; there were no PDF/XLSX decompression-bomb guards. | Generic 401 message; `/docs` disabled in prod; `POSTGRES_PASSWORD` from `.env` with localhost-only ports; chart text escaped; page and uncompressed-size limits. |

### Checked and found secure

| Area | Finding |
|---|---|
| **Exposed secrets** | No API keys, AWS keys or private keys in the source, config or built JavaScript. `backend/.env` holds a random 64-character secret and is git-ignored. AWS credentials come from the standard AWS chain, never from code. `VITE_*` variables contain no secrets. |
| **SQL injection** | All database access goes through SQLAlchemy with bound parameters. There is no string-built SQL; the only raw SQL is two constant statements. Injection strings in every search and filter return no extra rows (tested). |
| **Authentication** | JWT algorithm pinned (HS256 in dev, RS256 + JWKS for Cognito); issuer, audience, expiry and `token_use` verified; forged, `alg: none`, expired and malformed tokens rejected (tested). Dev sign-in can't run when `APP_ENV=prod` (startup check). |
| **Authorization** | Tenant scoping is centralized in `core/access.py`, and out-of-scope IDs return 404. Partner uploads are pinned to the partner's organization, and leadership is read-only (tested). |
| **Data handling** | Raw files are stored with SSE-KMS on S3 in prod and only served through the access-checked, audited download endpoint. Every upload, download, AI extraction, edit and approval is audited. Error responses never include stack traces or user input. |
| **Dependencies** | `pip-audit`: no known vulnerabilities. `npm audit`: 0 vulnerabilities. |

### Remaining risks and recommendations

- **Rate limits are per process.** With several API instances, add AWS WAF rate-based rules or API Gateway throttling.
- **Session tokens live in `sessionStorage`.** This is standard for a SPA and is cleared when the tab closes. The CSP and escaping above reduce the XSS risk that could expose them. For stronger protection, move to an HTTP-only cookie session behind a backend-for-frontend.
- **Prompt injection.** Uploaded documents are untrusted input to Claude. Mitigations: documents are wrapped as data, the model has no tools, evidence quotes are verified against the source, and a human approves every record.
- **Dev mode.** `AUTH_MODE=dev` lets anyone who reaches the API choose an account. It is blocked in production by configuration validation; never expose a dev instance publicly.
- **Not covered by this audit:** a real phone (tests used Chrome at phone dimensions), the Docker and AWS deployments (not run here), and live Cognito and Bedrock.
