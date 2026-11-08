# UniBuddy Backend

FastAPI backend for UniBuddy. Implemented: auth and role/campus authorization, PDF
upload and processing, embeddings, RAG chat with citations and abstention, forwarding
unanswered questions to faculty, ticket handling, announcements, notifications, and
dashboards. The code and its 158 pytest tests are complete. The live flow still needs
the approvals listed below before it can run against the dev project.

## Status checklist

Four states, kept separate on purpose. "Locally verified" means tests or local PostgreSQL
passed. It does not mean the live project was tested.

### Implemented (code in the repo)

- Auth: Supabase token verification (ES256/RS256), profile lookup, roles, campus rule, `GET /auth/me`
- Documents: upload (202), replace, publish, archive, detail, paged and filtered list, background worker
- Chat: grounded answers with citations or abstention, conversation list and messages, forward to faculty
- Tickets: paged list with filters, detail with timeline, take, status change and reply
- Announcements (scope rule), notifications (paged, mark read)
- Dashboards: student (exact counts), staff (SQL, RLS-scoped), management (SQL aggregates only)
- Provisioning: authority invites students and faculty into its own campus; audit trail
- Build: `pyproject.toml` with `uv.lock`; `requirements.txt` kept for pip deployment
- Provisioning safeguards: the email domain must be on the server-side allowlist
- Authentication UI and account flow (React + Vite in `frontend/`): login, registration request, invitation acceptance, set-password, forgot-password, one dashboard per role, an authority screen for invitations and registration approvals, and a Super Admin screen for authority and management accounts
- Role policy: students by approved registration, faculty and students by campus authority within campus, authority and management by Super Admin, Super Admin by one-time bootstrap only; the campus and role are never client-supplied (see "Roles, invitations and approvals")
  (`PROVISIONING_ALLOWED_EMAIL_DOMAINS`, exact match). An empty list fails closed with `503`.
  The campus and role come from the authority's profile and the endpoint, never from the
  client. Management cannot provision.

### Locally verified (no live project)

- Provisioning domain allowlist: exact match, subdomains refused, empty list fails closed,
  config parsing (`tests/test_provisioning.py`)
- Registration intake: domain allowlist, fail closed, identical receipt for repeat requests, no role or campus accepted (`tests/test_registration.py`, `tests/sql/registration_test.sql`)
- Frontend: role routing, domain and password checks, API error handling (13 unit tests); production build succeeds with no key-shaped values in the output; a signed-out visitor is redirected from a protected route to `/login` in the browser
  config parsing (`tests/test_provisioning.py`)

- 158 pytest tests pass under pip and under `uv`, on Python 3.11 and 3.14
- Migrations `20261108120000` to `20261108120900` parse under PostgreSQL's grammar
- Lifecycle and provisioning SQL assertions pass on PostgreSQL 17 with pgvector (`tests/sql/run_local_db_tests.sh`)
- RLS visibility matrix: 80/80 on a local database with the final policies
- The server starts with the worker lifespan, and the worker idles without a Gemini key

### Live verified (Mumbai dev project, ref in `.env`)

- Migrations `20261108120000` to `20261108120900` applied; the seeded RLS test data is kept
- RLS visibility matrix: 80/80 on the live project after migration 0800
- Function privileges: `service_role`, `authenticated` and `anon` match the intended grants
- `staff_dashboard_stats` and `management_ticket_stats` return real data
- Private `documents` bucket exists; a probe upload and a service-key insert succeeded, and the probes were removed
- Read-only checks, secret key, through the backend's own code paths: profile lookup returns
  the role and campus from the row; the management aggregate RPC returns real totals; a valid
  provisioning precheck returns `ok` and writes nothing; the audit table has 0 rows afterwards
  and the seeded data is unchanged (8 profiles)
- RLS visibility matrix re-run on the live project: 80/80
- Signed-in authority session via the magic-link method (secret key generates the link, publishable key exchanges it; no password changed, no email sent). Through the backend's real auth path: `/auth/me` returns role `authority` with a campus; tickets 2, documents 6, announcements 3 visible; `/dashboard/staff` 200; management and student dashboards 403; provisioning with an empty body 422 (no invitation); a garbage token 401. Side effect: a login session and two one-time token rows were created for the seeded authority user. Tokens were kept in memory and not stored.
- Publishable key accepted: six anonymous read or RPC requests (profiles, documents, campuses, both staff and management RPCs, audit table) each returned `42501` (permission denied for `anon`). Anonymous access is closed.
- Migration `20261108120900`: the three provisioning functions are callable only by `service_role`; `provisioning_audit` has RLS on and no grants to API roles. The provisioning endpoints have not been called live, so the audit table is still empty

### Verified status (2026-11-09)

**Verified by automated tests, and by minimal live or read-only checks**

- Backend tests: 218 pass. Frontend tests: 28 pass. The frontend production build succeeds.
- Gemini embeddings: a synthetic embedding returned 1536 dimensions. This was one live call.
- Gemini answers: a synthetic answer through the app's client returned text with `gemini-3.5-flash-lite`. This was one live call. `gemini-2.5-flash` and `gemini-2.5-flash-lite` returned 404 for this key, so neither is the default.
- The Leave of Absence Policy is published as university-wide and Ready: 10 pages, 23 chunks, all 1536-dimensional. The stored file matches the source PDF. This was read-only.
- The hosted API answers at `https://unibuddy-backend-demo.onrender.com/api/v1/health`. This was read-only. Its code version and whether it holds `GEMINI_API_KEY` were not checked.
- Chat (code and tests): answers come only from published documents, cite real sources and pages, and abstain without evidence. If the AI service fails, the question is saved with a reply that offers to send it to faculty, and it has no citations.
- Tickets (code and tests): taking, status changes, replies and notifications follow the role and status rules.

**Not verified**

- A real Student login, and student chat end to end in a browser: a cited answer, an unanswerable question, forwarding, and a faculty reply.
- Google sign-in. The Google Cloud and Supabase setup is not done.
- The Vercel frontend. It isn't deployed.
- The hosted backend's code version and its Gemini settings.
- OCR, and capacity for 3,000 or more users.

**Actions for you**

1. Restart the local API so the new default answer model loads.
2. Student account: from **Authority → Invitations**, invite one university mailbox you control, then set the password from the email link. You may send the invitation yourself.
3. Google sign-in: follow the Google Cloud and Supabase checklist. Keep the client secret out of chat and out of frontend code.
4. Hosted API: in Render, set `GEMINI_API_KEY` as a private variable, set `GEMINI_CHAT_MODEL=gemini-3.5-flash-lite`, and redeploy, if you want the hosted API to answer questions.
5. Hosted frontend: import the repo in Vercel with root directory `frontend`, if you want a hosted frontend.

### Not applied

- Nothing pending on the dev project. Live provisioning is not yet exercised; see the blocked items

### Blocked (cannot be verified without the items listed)

- **Applied to dev (approved):** migrations `20261109120000` and `20261109130000`. Verified read-only: the seeded 8 profiles and 8 auth users are unchanged, no registration rows, no Super Admin, the bootstrap function runs only as the owner.
- **Migration `20261109140000`** (university-wide scope trigger): tested locally, not applied, needs your approval
- **Super Admin account**: not created. Needs the bootstrap runbook, after your approval of the invitation
- **Abuse protection for the public registration endpoint** (host rate limit or CAPTCHA): not built
- **Supabase email templates, redirects and OTP expiry**: dashboard settings, not configured yet
- **Live invitation** to `yash.g26398@nst.rishihood.edu.in`: needs your separate go-ahead, and the Supabase Auth settings above

- **Gemini key** (`GEMINI_API_KEY`): live embeddings, live answers and citations, the upload-to-answer flow, and worker processing of real PDFs
- **Live provisioning and Gemini-dependent flow**: see the one-batch checklist. The signed-in session blocker is resolved (below); see **Verified status (2026-11-09)** below for the current blockers
- **Sample campus PDF(s)**: retrieval tuning (similarity threshold, top-k) and a meaningful end-to-end test
- **Live provisioning (invite sends a real email)**: needs the publishable key for the authority session, the SMTP and redirect setup described in the one-batch checklist, a controlled inbox on an allowlisted domain. The domain allowlist is now implemented; the policy beyond it is your call
- **OCR**: unavailable. It needs a container runtime with Tesseract, which is not set up
- **Deployment**: no hosting chosen, no Render service, and no worker runtime. The worker plan is in the README
- **Capacity (3,000+ daily users)**: not verified. Needs a load test against a deployed environment

### One-batch setup checklist (do these in order, then tell me "ready")

Everything below is needed before the live checks that depend on keys, PDFs and email.
Secrets go into `backend/.env` or the Supabase dashboard only. Never paste them into chat.

1. **Env values in `backend/.env`.** Add these four lines, with real values:
   - `SUPABASE_PUBLISHABLE_KEY`: Project Settings → API Keys → publishable key.
   - `GEMINI_API_KEY`: your Google Gemini API key from Google AI Studio.
   - `PROVISIONING_ALLOWED_EMAIL_DOMAINS`: the domain your controlled test inbox uses, for
     example `yourdomain.test`. Use exact domains, comma-separated. Leave it empty and
     provisioning stays disabled.
   - Keep `SUPABASE_STORAGE_BUCKET=documents`.
2. **Invitation email (Supabase dashboard).**
   - Authentication → Emails: check the "Invite user" template.
   - Project Settings → Authentication (SMTP): for a controlled test, either use the built-in
     mailer, which is rate-limited and may only reach project-team addresses, or enter your
     own SMTP provider.
   - Authentication → URL Configuration: set the Site URL to `http://localhost:3000` and add
     the invite landing page to the redirect allow-list.
3. **Controlled test inbox.** An address you own on the allowlisted domain, for example a
   plus-address such as `you+unibuddy-test@yourdomain.test`.
4. **Sample campus PDF.** Put one real PDF at a path I can read, for example
   `backend/sample_data/campus-policy.pdf`. The `sample_data` folder is not in git. Tell me
   the path, and say whether it can be shared with the model.
5. **Authority test session.** I will sign in as the seeded authority user
   `rlstest-authority-c1@example.com` with the publishable key. No password is changed.
6. Tell me "ready". I will then run, in one batch:
   - a live upload, worker processing, publish, a cited answer, an abstention, and a forward
     to faculty, on the dev project, using the sample PDF;
   - one provisioning invite to your controlled inbox, then the profile row and one audit row;
   - the user-scoped reads through the publishable key with the real session.

Deployment, capacity and OCR are not in this batch. See their sections below.

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
Supabase and Gemini test doubles, and real PDFs generated with PyMuPDF. They make no
network calls. The HTTP client tests use mocked transports, so they check request
shape, not live Supabase or Gemini behaviour.

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
- With no `GEMINI_API_KEY`, uploads are still accepted. Documents wait in the queue, and
  `processing_note` says why. The worker does not call Gemini, and nothing is faked.
- **Embedding space.** Document chunks and questions both use `gemini-embedding-001` at 1536 dimensions.
  Chunks are embedded as `RETRIEVAL_DOCUMENT` and questions as `RETRIEVAL_QUERY`. Every processing run
  re-embeds the whole document, so one document never mixes models. Changing the embedding model or
  dimension later means re-embedding every document. Never compare vectors from two models.

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

1. Live Gemini calls (embeddings and answers). Blocked: no `GEMINI_API_KEY` yet.
2. The upload-to-answer flow on the dev project: upload, worker processing, publish, a
   cited answer, an abstention, and a forward to faculty. Blocked: needs the Gemini key,
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

**Other ways accounts exist today.** Authority and management accounts are created by Super
Admin's invitation, and Super Admin itself by the one-time bootstrap (see "Roles, invitations and
approvals"). Any correction to an existing profile is still made by a database owner. The
`authenticated` role can read profiles but not write them. The `service_role` key can execute
only the provisioning and approval functions, and read profiles.

**Cross-campus access.** `cross_campus_record_access` is `false` for every user, and nothing
sets it. Management reporting uses aggregates only. Management cannot provision accounts.

**Before production.**

- Confirm the production domain list for `PROVISIONING_ALLOWED_EMAIL_DOMAINS`. Exact-match
  allowlisting is implemented, and an empty list is disabled.
- Decide whether invitations need approval from a second person, and build an audit read
  path for the owners of the process.
- Build the worker deployment (see below).

## Authentication: invitations, registration and the React app

**Implemented**

- **Frontend:** a separate React + Vite app in `frontend/`. Pages: `/login`, `/register`,
  `/accept-invitation`, `/set-password`, `/forgot-password`, and one dashboard per role. The
  friend-owned root `index.html` is untouched. See `frontend/README.md`.
- **Sign-in:** Supabase Auth email and password. FastAPI verifies the token and loads the
  role and campus from `profiles`. `GET /auth/me` is the source of truth for the redirect.
- **Invitations:** `POST /provisioning/students` and `POST /provisioning/faculty`. Only an
  authority user can call them, and only for its own campus. The email must be on
  `PROVISIONING_ALLOWED_EMAIL_DOMAINS`. The invitation itself is a Supabase Auth invite.
- **Student registration request:** `POST /auth/registrations`. Public, restricted to the
  allowlisted domain, returns the same answer whether or not the address is known, and grants
  nothing. Stored in `registration_requests` (migration `20261109120000`, unapplied).

**Not implemented (waiting on decisions below)**

- Approving a registration request, which is what turns a request into an invitation.
- Inviting authority or management accounts, and creating Super Admin.

**Supabase Auth settings (dashboard, once you're ready to test)**

These are dashboard steps. Enter SMTP credentials only in the dashboard.

1. **Site URL:** `http://localhost:5173`.
2. **Redirect URLs:** add `http://localhost:5173/accept-invitation`.
3. **Invite email template.** The default template sends tokens in the URL fragment, which the
   accept page can't read. Use a link that carries the token hash instead:
   `{{ .SiteURL }}/accept-invitation?token_hash={{ .TokenHash }}&type=invite`
   (verify the variable names against the dashboard's template help).
4. **Reset email template:** the same form with `type=recovery`.
5. **Expiry:** set the email link expiry to 24 hours or less, to meet the time-limited rule.
   Supabase tokens are single-use.
6. **Password policy:** set the minimum length to 12, to match the UI.
7. **SMTP:** choose the built-in mailer for tests or your own provider. The built-in mailer
   is rate-limited and may only reach project-team addresses.
8. **Backend CORS:** add `http://localhost:5173` to `ALLOWED_ORIGINS` in `backend/.env`.

**Verified locally:** the SQL for the registration table (`tests/sql/registration_test.sql`),
the intake service and route (173 backend tests), and the frontend's unit tests and
production build. **Not verified:** any live invitation, email delivery, the email links, or
the password-setting path. Each needs your go-ahead and the settings above.

## Roles, invitations and approvals (implemented)

**University-wide content.** Only Authority may create, publish, replace or archive
university-wide documents. Faculty can't set that scope, so they can't publish it. The API checks
this in the document service and the upload route. Migration `20261109140000_university_scope_guard.sql`
adds a database trigger with the same rule (unapplied, approval needed). Super Admin can't upload
documents, because uploading needs document access, and Super Admin has no academic-record access.
That is an open question.

**Role policy as built**

| Role | Created by | Campus | Notes |
|---|---|---|---|
| Student | Approved registration (a campus authority approves), or a campus authority's invitation | The approving or inviting authority's campus | A registration is a pending request and grants nothing. |
| Faculty | A campus authority's invitation | The inviting authority's campus, and a department on it | |
| Authority | Super Admin's invitation | Chosen by Super Admin, required | Campus authority cannot create authority accounts. |
| Management | Super Admin's invitation | Optional | Aggregate-only. `cross_campus_record_access` stays false. |
| Super Admin | One-time bootstrap only, from the database owner's session | None | Account provisioning and the account list. No academic records. |

No client ever supplies its own role or campus. The endpoint sets the role. The campus comes
from the approver's or inviter's profile, or, for authority accounts only, from Super Admin's
choice, validated in the database.

**Endpoints (all under `/api/v1`)**

| Method and path | Who | What |
|---|---|---|
| `POST /auth/registrations` | public | Stores a pending student request. Same answer for repeat requests. |
| `GET /provisioning/registrations` | authority | Pending requests. |
| `POST /provisioning/registrations/{id}/approve` | authority | Invites the student to the authority's campus. Sends a real email. |
| `POST /provisioning/registrations/{id}/reject` | authority | Rejects with an optional reason. |
| `POST /provisioning/students`, `/provisioning/faculty` | authority | Invites into the authority's campus. Sends a real email. |
| `GET /provisioning/departments` | authority | Departments on the authority's campus only. |
| `POST /provisioning/authority`, `/provisioning/management` | Super Admin | Invites with a campus chosen by Super Admin (required for authority). Sends a real email. |
| `GET /provisioning/campuses` | Super Admin | Campus list for the invitation form. |
| `GET /admin/accounts` | Super Admin | Account fields only, from `super_admin_list_accounts()` (the database re-checks the role). |

**Super Admin bootstrap runbook (one time, after migration 20261109130000 is approved and applied)**

1. Invite the Super Admin's account from the Supabase dashboard (Authentication → Users →
   Invite). This sends an email, so do it deliberately, with the university address.
2. Copy that user's UUID from the dashboard.
3. In the SQL editor, as the owner, run:

   ```sql
   select public.bootstrap_super_admin('<user-uuid>', 'name@nst.rishihood.edu.in');
   ```

   It refuses a second Super Admin, a non-university domain, and an unknown user. No API role
   can run it. Record the run in your own change log; the function also writes an audit row.

**Verified locally:** the migration's SQL (`tests/sql/super_admin_test.sql`, plus the older
suites, all in the local runner); 191 backend tests covering the invitation rules, approval and
rejection, and the route boundaries; 14 frontend tests and a production build.

**Not verified:** any live invitation, email delivery, the invite and reset links, password
setting, sign-in with a new account, the Super Admin bootstrap, and the live approval flow.

## One-hour demo: prerequisites and runbook

**What the demo shows, in order:** sign in → a faculty or authority user uploads and publishes one
approved campus PDF → a student asks a question and gets a grounded answer with its source and page →
a question the PDF cannot answer is abstained and sent to faculty → faculty sees the ticket, replies,
and changes its status.

**Nothing below has been run live yet.** Local tests and the browser check of protected routes
pass. The live steps need the items marked as blockers.

**Prerequisites (you do these; never paste secrets into chat)**

1. Approve the two pending migrations, `20261109120000` and `20261109130000`. Verified dry run: exactly those two.
2. In `backend/.env`, set `GEMINI_API_KEY` (an older `OPENAI_API_KEY` line is no longer used). Add
   `http://localhost:5173` to `ALLOWED_ORIGINS`.
3. Create `frontend/.env.local` from `frontend/.env.example`, with the publishable key and the API URL.
4. Give me one approved, public campus PDF (path). Its text will be sent to Google Gemini for embeddings and,
   when answering, excerpts will be sent for generation. Approve that explicitly.
5. Approve the controlled invitations (see the report for the addresses and the sequence). Invitees set
   their own passwords. No seeded account's password is changed.

**Runbook once the prerequisites are met**

1. Start the API: `uv run uvicorn app.main:app --reload` (from `backend/`).
2. Start the app: `npm run dev` (from `frontend/`), then open `http://localhost:5173/login`.
3. Sign in as the faculty or authority user. Upload the PDF on the Documents page. Wait until its status
   reads Ready (the worker processes it in the web process). Publish it.
4. Sign in as the student. Ask a question the PDF answers. The answer must show its source and page.
5. Ask a question the PDF does not answer. The answer must say it could not be found, with a send-to-faculty
   button. Send it, choosing a department on the student's campus.
6. Sign in as faculty. Open the ticket, take it, reply, and move it to In progress or Resolved.

**Cost and data notes.** Each document is sent to Google Gemini for embeddings once. Each question is
embedded, and the relevant excerpts are sent for generation. Set a spend limit on the Google Cloud or AI Studio
project first. Keep `DOCUMENT_WORKER_ENABLED=true` for the demo, and upload only the approved PDF, because
the worker processes every queued upload with the key.

## Supabase dashboard checklist (click by click)

Menu names change between dashboard versions. Use the search box if a name differs. Do these on the dev project only.

1. **Site URL.** Authentication → URL Configuration → *Site URL* → `http://localhost:5173` → Save.
2. **Redirect URLs.** Same page → *Redirect URLs* → Add URL → `http://localhost:5173/accept-invitation` → Save.
3. **Invite email template.** Authentication → Email Templates → *Invite user*. Replace the confirmation
   link with the token-hash link:
   `{{ .SiteURL }}/accept-invitation?token_hash={{ .TokenHash }}&type=invite`
   → Save. (Leave the rest of the template as it is.)
4. **Reset password template.** Authentication → Email Templates → *Reset password*:
   `{{ .SiteURL }}/accept-invitation?token_hash={{ .TokenHash }}&type=recovery` → Save.
5. **Link expiry (24 hours or less).** Authentication → Sign In / Providers → *Email* (or the Auth settings
   page, depending on version) → find *OTP expiry* / *Email OTP expiration* → `86400` seconds → Save.
6. **Password minimum 12.** Authentication → Sign In / Providers → *Email* (or Password settings) →
   *Minimum password length* → `12` → Save.
7. **Email delivery.** Project Settings → Authentication → *SMTP Settings*. Either leave the built-in mailer
   for a quick test (rate-limited; it may only reach project-team addresses) or enter your own provider's
   host, port, username and password here. Enter credentials only in this dashboard. Send one test email
   if the page offers it.
8. **Check nothing was created.** Authentication → Users: no new users should exist until you approve
   the invitations.

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
      gemini_client.py            Gemini embeddings and answers (server-side only)
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
      providers.py                Cached Supabase and Gemini clients
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
