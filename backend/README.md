# UniBuddy Backend

FastAPI backend for UniBuddy. Implemented: auth and role/campus authorization, PDF
upload and processing, embeddings, RAG chat with citations and abstention, forwarding
unanswered questions to faculty, ticket handling, announcements, notifications, and
dashboards. The code and its 158 pytest tests are complete. The live flow still needs
the approvals listed below before it can run against the dev project.

## Setup

From the `backend/` directory. Two equivalent ways:

With `uv` (recommended; the lockfile pins every dependency, Python 3.11+):

```bash
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
```

With pip (the deployment path; `requirements.txt` mirrors `pyproject.toml`):

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

When you change a dependency, update `pyproject.toml`, run `uv lock`, and regenerate
`requirements.txt` with
`uv export --frozen --no-hashes --no-emit-project --no-dev --format requirements-txt`.
Both files must list the same runtime versions. Dev-only tools (pytest) are in the `dev`
group.

Copy the environment template:

```bash
cp .env.example .env
```

`.env` is git-ignored. Leave the Supabase values as placeholders if you only
want the health endpoint and tests.

## Run

```bash
uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000`. Swagger UI is at `http://localhost:8000/docs`.

```bash
curl http://localhost:8000/api/v1/health
```

```json
{"status": "ok", "app": "UniBuddy Backend", "env": "development"}
```

## Test

```bash
pytest
```

Expected: 158 tests pass. The tests use a locally generated signing key, in-memory
Supabase and OpenAI test doubles, and real PDFs generated with PyMuPDF. They make no
network calls. The HTTP client tests use mocked transports, so they check request
shape, not live Supabase or OpenAI behaviour.

## Authentication and authorization

Protected requests send `Authorization: Bearer <access token>`, where the token
is the one Supabase Auth issues to the logged-in user.

`GET /api/v1/auth/me` returns the caller's profile:

```json
{
  "id": "…", "email": "…", "full_name": "…", "role": "faculty",
  "campus_id": "…", "department_id": "…", "cross_campus_record_access": false
}
```

How the backend identifies the caller:

1. The token signature is checked against Supabase's public signing keys, from
   `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`. Only ES256 and RS256 are
   accepted. HS256 and `alg: none` are rejected.
2. The audience must be `authenticated`, the issuer `<SUPABASE_URL>/auth/v1`,
   and `exp`, `iat` and `sub` must be present.
3. `sub` is looked up in `profiles` with the secret key. Role, campus,
   department and `cross_campus_record_access` come from that row. Token claims such as
   `user_metadata` are never used for authorization.
4. A valid token with no profile row gets `403`.

FastAPI dependencies live in `app/middleware/auth.py`: `get_current_user` and
`require_roles("faculty", ...)`.

### Access rules (working defaults)

| Data | Rule |
|---|---|
| Published public student documents | Every authenticated user across all campuses. Not filtered by campus. |
| Published staff-only documents and staff-only announcements | Faculty and authority on the item's campus. Any campus only when `scope = university_wide`. Management has no access. |
| Draft and archived documents | Uploader, plus authority reviewers on the item's campus (any campus only when `scope = university_wide`). Management has no access. |
| Campus-scoped content | `campus_id` is required unless `scope = university_wide`. |
| Tickets (individual) | Student sees their own. Assigned faculty sees assigned tickets. Faculty sees their campus and department queue. Authority sees its own campus. Other campuses only with `cross_campus_record_access`. |
| Profiles (individual) | Own profile. Faculty and authority see their own campus. Other campuses only with `cross_campus_record_access`. |
| `cross_campus_record_access` | Explicit grant set by the backend, allowed only for `management`. Never set at signup. It covers individual tickets and profiles only. |
| Management reporting | Aggregate statistics only (see below). Does not use `cross_campus_record_access`. |

### Management reporting

Management sees aggregate statistics: campus and department totals, resolution
rates, and faculty response times. Management does not read staff-only or draft
document or announcement content for reporting. Reporting never reads individual
rows through RLS. The backend computes aggregates with the secret key and
returns counts and rates, not record contents. That code arrives in the dashboard
milestone, and it must check `role = management` before running.

Individual ticket or profile access for management needs the separate
`cross_campus_record_access` grant. Analytics does not imply it.

## Supabase development project setup

Use a separate development project. Do not use a production project for this.

1. **Create the project.** Sign in at supabase.com, then choose New project.
   Name it something like `unibuddy-dev`. Pick the region closest to your campuses.
   Set a database password and store it in a password manager. This backend does not
   need the password yet.
2. **Copy the Project URL.** In the project, go to Project Settings → API. Copy
   *Project URL*. It looks like `https://<project-ref>.supabase.co`.
3. **Copy the secret API key.** Go to Project Settings → API Keys (labels vary;
   look for the *Secret keys* section). Copy the default secret key, which starts
   with `sb_secret_`. It bypasses row-level security, so treat it like a password.
4. **Check the JWT signing keys.** Go to Project Settings → JWT Keys. The current
   signing key should be ECC (P-256), which is ES256. The backend verifies tokens
   with the public keys from `/auth/v1/.well-known/jwks.json`, which lists only the
   asymmetric keys. Tokens signed by the older HS256 key are rejected. Users sign
   in again to get an ES256 token.
5. **Set the local variables.** From `backend/`, copy the template, then edit
   `.env` in a text editor:

   ```bash
   cp .env.example .env
   ```

   Set these two lines, and leave the rest as they are:
   ```
   SUPABASE_URL=https://<your-dev-project-ref>.supabase.co
   SUPABASE_SECRET_KEY=sb_secret_<paste your key here>
   ```
   Save the file. Never paste these values into chat, commit them, or add them to
   the frontend.

   If you already created `.env` from an earlier version, rename
   `SUPABASE_SERVICE_ROLE_KEY` to `SUPABASE_SECRET_KEY` and paste the new
   `sb_secret_` value. The old name is no longer read.

6. **Confirm `.env` is ignored by git.** From the repository root, run:

   ```bash
   git check-ignore -v backend/.env
   ```

   It should print a matching rule. If it prints nothing, stop before committing anything.
7. **Create test users when migrations are applied.** Go to Authentication → Users
   → Add user → Create new user. Tick *Auto Confirm User* so you can sign in without
   email verification. Copy the user's UUID.
8. **Create a test profile.** After migrations are applied, open the SQL Editor and
   run this with your own values:

   ```sql
   insert into public.campuses (name, code) values ('Test Campus', 'test');

   insert into public.profiles (id, email, full_name, role, campus_id)
   values (
     '<user-uuid-from-step-6>',
     '<same-email>',
     'Test Faculty',
     'faculty',
     (select id from public.campuses where code = 'test')
   );
   ```

Then call `GET /api/v1/auth/me` with that user's access token. You should see the
profile. The migrations are not applied yet, and I will not run them until you
approve applying them to this development project.

## Document and chat flow: endpoints and UI mapping

All endpoints are under `/api/v1`. Roles are checked on the server for every route.
List endpoints return `{"items": [...], "total": n, "limit": l, "offset": o}`. `limit`
defaults to 20 and is capped at 100. Filters narrow the rows the caller can already see.
They never widen access.

| Method and path | Roles | What it does | Frontend screen it serves |
|---|---|---|---|
| `POST /documents` (multipart: `file`, `title`, `visibility`, `scope`, `department_id`) | faculty, authority | Stores the PDF and queues it. Returns **202** with `processing_status: pending`. | None yet. Upload screen needed. |
| `POST /documents/{id}/replace` (multipart: `file`, `title?`) | uploader (faculty), same-campus authority | Queues a new version. It stays a draft until published. Returns **202**. | None yet. |
| `POST /documents/{id}/publish` | uploader (faculty), authority | Publishes a ready draft. If it replaces another version, that version is archived in the same database step. | None yet. |
| `POST /documents/{id}/archive` | uploader (faculty), same-campus authority | Archives a draft or published document. Idempotent. | None yet. |
| `GET /documents/{id}` | any signed-in user | One document the caller may see, with `processing_note` and `last_error`. | Document status polling. |
| `GET /documents` (`limit`, `offset`, `processing_status`, `publication_status`, `visibility`, `scope`, `campus_id`, `department_id`) | any signed-in user | Paged list the caller may see. | Faculty/authority document list (new). |
| `POST /chat/ask` `{question, conversation_id?}` | student | Retrieves permitted chunks as the caller, answers with citations, or abstains. Saves both messages. | AI Assistant chat (`ask()` in `index.html`). |
| `GET /chat/conversations` (paged) | student | The student's own conversations. | Chat history (`S.hist`). |
| `GET /chat/conversations/{id}/messages` (paged) | student | Messages in one of the student's conversations. | Chat history view. |
| `POST /chat/messages/{id}/forward` `{department_id, priority, description?}` | student | Creates a submitted ticket for the student's campus. One ticket per question. | "Forward to Faculty" modal (`ms` action). |
| `GET /tickets` (`limit`, `offset`, `status`, `priority`, `department_id`, `campus_id`, `assigned=me\|unassigned`) | any signed-in user | Paged tickets the caller may see. | My Queries list (`S.tickets`) and faculty ticket table. |
| `GET /tickets/{id}` | any signed-in user | Ticket detail with its timeline. | Ticket detail (`detail()`). |
| `PATCH /tickets/{id}` `{status?, reply?, take_ticket?}` | faculty, authority | Takes a ticket, changes status, or replies. The student gets a notification. | Faculty Respond/Resolve actions. |
| `GET /announcements` (paged; `audience`, `scope`, `campus_id`, `is_important`) | any signed-in user | Announcements the caller may see. | Announcements feed (`ANN`). |
| `POST /announcements` | faculty, authority | Publishes an announcement. University-wide scope is authority only. | None yet. |
| `GET /notifications` (paged; `is_read`) | any signed-in user | The caller's notifications. | Notification bell (`S.notifs`). |
| `PATCH /notifications/{id}/read` | any signed-in user | Marks one of the caller's notifications read. | Notification bell. |
| `GET /dashboard/student` | student | Real counts of the student's questions and tickets. | Student dashboard tiles (`dash()`). |
| `GET /dashboard/staff` | faculty, authority | Counts over the tickets and documents the caller can see: open, resolved, unassigned queue, assigned to me, by department, average first-response hours. | Faculty and authority dashboards (new). |
| `POST /provisioning/students` `{email, full_name, department_id?}` | authority | Invites a student into the authority's own campus. **Sends a real invitation email.** | Authority user management (new). |
| `POST /provisioning/faculty` `{email, full_name, department_id}` | authority | Invites a faculty member into the authority's own campus. Department is required and must be on that campus. **Sends a real invitation email.** | Authority user management (new). |
| `GET /management/stats` | management | Campus and department totals, resolution rates, average first-response hours, computed in the database. No record contents. | Management dashboard (placeholder today). |

**Ticket status values** are the database values `submitted`, `assigned`, `in_progress`,
`resolved`. The frontend shows "Submitted", "Assigned", "In Progress", "Resolved". The
frontend should map the labels.

**Document processing.** Uploads are stored and queued. A worker claims them, so a restart
or a second worker never processes the same document twice:

- `claim_document_jobs` uses `FOR UPDATE SKIP LOCKED`. A claim whose worker stopped expires
  after `DOCUMENT_LEASE_SECONDS` (default 600) and is claimed again.
- Processing is safe to repeat. Old chunks are deleted before new ones are inserted.
- A PDF that cannot be read, or has no text layer, fails at once with a reason. A temporary
  failure (AI service, storage, database) returns the document to the queue. After
  `DOCUMENT_MAX_ATTEMPTS` (default 3) it fails with the reason recorded in `last_error`.
- With no `OPENAI_API_KEY`, uploads are still accepted. Documents wait in the queue, and
  `processing_note` says why. The worker does not call OpenAI, and nothing is faked.

Run the worker in the web process (the default, when `DOCUMENT_WORKER_ENABLED=true`), or as
its own process, which is the better option for Render:

```bash
python -m app.worker
```

**Answer rules.** Retrieval uses `match_document_chunks`, which runs as the caller, so
RLS decides which chunks can be returned. Chunks below `RETRIEVAL_MIN_SIMILARITY` are
dropped. If nothing is left, the model is not called and the response abstains. If the
model replies `INSUFFICIENT_EVIDENCE`, or gives no citation to a retrieved source, the
response also abstains. Citations are built from the retrieved chunk's document and page,
never from the model's text. Abstained responses set `escalation_available: true`.

### OCR for scanned PDFs: unavailable

Status: **unavailable**. Scanned PDFs (no text layer) fail with a clear reason. OCR is not
deployed. It would need:

- the Tesseract binary and its language data installed on the host. PyMuPDF does not
  include them, and this backend's requirements are pure Python wheels;
- a container runtime for the worker, for example a Render Docker service with
  `apt-get install tesseract-ocr tesseract-ocr-eng`. No container is set up yet;
- an OCR timing test on real campus scans, since OCR is much slower than text extraction.

Remaining dependency: choose the hosting runtime for the worker. Only then decide whether
scanned PDFs are common enough to justify the image size and latency. No container or
paid service has been created for this.

### Production worker (plan, not deployed)

Development runs the document worker inside the web process, which is the default when
`DOCUMENT_WORKER_ENABLED=true`. Before production, run the worker as its own process, so
slow document processing cannot delay web requests and the worker can be scaled separately:

- The web service sets `DOCUMENT_WORKER_ENABLED=false`.
- A separate background-worker service runs `python -m app.worker` with the same
  environment. Several workers are safe, because the claim uses `SKIP LOCKED`.

Nothing has been created for this. It would be a paid service, so it waits for your
decision on hosting.

### Live setup status

Applied to the dev project (`unibuddy-dev`, ref in `.env`):

- migrations `20261108120000` to `20261108120800`, including `20261108120800_document_lifecycle_and_scale.sql`
- the private `documents` Storage bucket
- the seeded RLS test data (8 profiles, documents, tickets). It is kept on purpose.

Verified on the live dev project: the 80-check RLS visibility matrix passes, and the
staff dashboard and management aggregate return real data for the seeded users.

**Live checks not yet run, and why:**

1. Live OpenAI calls (embeddings and answers). Blocked: no `OPENAI_API_KEY` yet.
2. The upload-to-answer flow on the dev project: upload, worker processing, publish, a
   cited answer, an abstention, and a forward to faculty. Blocked: needs the OpenAI key,
   and real campus PDFs for meaningful answers.
3. User-scoped reads through the publishable key with a real signed-in session.
   Blocked: no `SUPABASE_PUBLISHABLE_KEY` yet. Until then the RLS checks used SQL role
   impersonation, not HTTP sessions.
4. The worker's storage download and processing against real objects. Blocked by item 1.
5. Real campus PDFs, for tuning the similarity threshold and top-5 limit. Blocked: none
   provided yet.
6. Production deployment and the worker runtime. Blocked: hosting not chosen. Development
   runs the worker in the web process.
7. The 3,000+ daily-user target. Blocked: needs a load test against a deployed environment.

Keys go in `backend/.env` only. Do not paste them into chat.

### Capacity: measured so far

These were measured locally on one machine with a 200,000-ticket synthetic dataset. They
are single runs with no concurrency. They are not production evidence.

- Management aggregate, all tickets: about 0.13 s, returns about 900 bytes.
- Authority staff dashboard, 100,000 visible tickets: about 3.2 s before the RLS subquery
  rewrite, about 0.15 s after it.

**Not verified:** the 3,000+ daily-user target. That needs a load test through the deployed
API, against the real Supabase plan, with concurrent users and real documents. The
`count=exact` list totals also have a cost that has not been measured on a large dataset.

### Not done yet

- OCR for scanned PDFs (see above), re-running a failed document from the API, and deleting
  documents. Archiving is supported; hard deletion is not.
- Pagination is in place, but keyset pagination is not. Large offsets will get slower.
- The similarity threshold of 0.3 and the top-5 limit are starting values, not tuned
  against real campus documents.
- Load testing, rate limiting and caching.

## Accounts, roles and campus assignment

**Who can onboard whom.** An authority user can invite students and faculty into its own
campus, through `POST /provisioning/students` and `POST /provisioning/faculty`. Nothing
else can create accounts through the API, and nothing can create authority or management
accounts through the API.

**What the caller controls.** Only the invitee's email, full name, and (for faculty
or optionally for students) a department. The role comes from the endpoint. The campus is
always the authority's own, read from its profile. Any other field, including `role`,
`campus_id`, `all_campuses_access`, `cross_campus_record_access`, `uploaded_by`, or an owner
field, makes the request fail with `422` before anything is sent. A contract test
(`tests/test_request_contracts.py`) keeps this true.

**Checks, in order.**

1. The database precheck (`provisioning_precheck`). It verifies that the actor is an
   authority user with a campus, that the role is student or faculty, that the department
   belongs to that campus, and that no profile has the email yet. A rejection is written to
   the audit trail, and no invitation is sent.
2. The Supabase invitation (`/auth/v1/invite`). This sends a real email. An email that
   already has a login is refused, and the refusal is audited.
3. The database completion (`provisioning_complete`). It creates the profile with the
   authority's campus and `cross_campus_record_access = false`, and audits the invitation.
   If this step fails, the new login is deleted again and the compensation is audited. If
   that deletion fails too, the audit records `cleanup_failed` for manual follow-up.

**Audit trail.** Table `provisioning_audit` (migration `20261108120900`). Every rejection,
invitation, failure, and compensation is recorded. Only the database owner can read it, and
no API exposes it yet.

**Other ways accounts exist today.** Management and authority accounts, and any correction
to an existing profile, are still created by a database owner (SQL editor or CLI). The
`authenticated` role can read profiles but not write them. The `service_role` key can only
execute the three provisioning functions and read profiles.

**Cross-campus access.** `cross_campus_record_access` is `false` for every user, and nothing
sets it. Management reporting uses aggregates only. Management cannot provision accounts.

**Before production.**

- Decide the email policy. Right now any well-formed email can be invited. Restricting to
  the university domain or to pre-approved lists is a product decision.
- Decide whether provisioning needs approval from a second person, and build an audit read
  path for the owners of the process.
- Build the worker deployment (see below).

## Open decisions

- **`cross_campus_record_access`:** decided, no user holds it. It stays `false` for
  everyone, and nothing in the backend sets it. Management reporting stays aggregate-only.
- **Who sets `scope`:** the uploader or publisher chooses `campus` or `university_wide`.
  Confirm whether a university-wide choice needs approval.

## Database (Supabase)

Migration `20261108120900_campus_provisioning.sql` is **not applied** to the dev project. It
adds `provisioning_audit` and three service-only functions. It has been tested on a local
PostgreSQL 17 database (`tests/sql/run_local_db_tests.sh`), and needs your approval before
it is applied.

Schema lives in `supabase/migrations/` as numbered SQL files. They have been parsed
with PostgreSQL's grammar but **not applied to any database**. Row-level security
policies are reviewed, not yet exercised against a live database.

Tables: `campuses`, `departments`, `profiles` (roles: student, faculty, authority,
management), `documents` and `document_chunks` (pgvector, 1536 dimensions),
`conversations` and `messages`, `tickets` and `ticket_events`, `announcements`,
`notifications`.

To apply them, once approved:

- Supabase CLI: `supabase link --project-ref <your-dev-ref>`, then `supabase db push`
  from `backend/`, or
- SQL Editor: run each file in `supabase/migrations/` in filename order.

The first migration enables pgvector (`create extension if not exists vector`).

### Table privileges

The project has the Data API on, automatic table exposure off, and RLS on. New
tables are not exposed by default, so every privilege the backend or users need
must be granted explicitly in the migrations. Nothing is granted to `anon`.

| Role | Privilege | Why |
|---|---|---|
| `service_role` (used by the secret key) | `USAGE` on schema `public` | Lets the backend reach the schema through the Data API. |
| `service_role` | `SELECT` on `profiles` | `/auth/me` profile lookup. RLS is bypassed for this role. |
| `authenticated` (signed-in users) | `USAGE` on schema `public` | Needed for signed-in reads under RLS. |
| `authenticated` | `SELECT` on `campuses`, `departments`, `profiles`, `documents`, `document_chunks`, `conversations`, `messages`, `tickets`, `ticket_events`, `announcements`, `notifications` | Each table's RLS policy decides which rows are returned. The grant only allows the read to be attempted. |
| `authenticated`, `service_role` | `EXECUTE` on the `app_*` helpers and `can_read_document()` | Called from RLS policies. |

Migration `20261108120700_backend_operations.sql` adds the write and read-back grants
the endpoints use. It is applied to the dev project.
Migration `20261108120800_document_lifecycle_and_scale.sql` (applied to the dev project) adds
`DELETE` on `document_chunks` for reprocessing, `EXECUTE` on the job and aggregate
functions, and the RLS subquery rewrite.

Assumption to verify after applying: the secret key runs as the `service_role`
Postgres role. If the profile lookup returns an empty result for a known user, check
that assumption first, and then check this table.

## Project layout

```
backend/
  app/
    main.py                       FastAPI app, CORS, error mapping, router registration
    config.py                     Settings from environment variables / .env
    ai/
      pdf_extractor.py            PyMuPDF page-wise text extraction
      chunking.py                 Page-aware chunking
      openai_client.py            Embeddings and chat completions (server-side only)
      rag.py                      Evidence selection, prompt, citation and abstention rules
    middleware/auth.py            Session and role dependencies
    routes/                       One module per area: auth, documents, chat, tickets,
                                  announcements, notifications, dashboards
    worker.py                     `python -m app.worker`: standalone document worker
    services/
      document_worker.py          Claims and processes queued documents (retries, attempt cap)
      token_verifier.py           Supabase JWT verification (JWKS, ES256/RS256)
      authorization.py            Campus access rule
      supabase_client.py          PostgREST, RPC and Storage (secret or user-scoped calls)
      providers.py                Cached Supabase and OpenAI clients
      documents.py chat.py tickets.py announcements.py notifications.py dashboards.py
    repositories/profiles.py      Profile lookup via Supabase REST
    schemas/                      Pydantic request and response models, incl. Page envelope
  supabase/migrations/            Schema, RLS, indexes, grants (0000-0800 applied to dev; 0900 pending approval)
  tests/                          pytest suite (158 tests) and in-memory test doubles
  tests/sql/                      SQL assertions and a local-only database runner
  requirements.txt
  .env.example
  pytest.ini
```
