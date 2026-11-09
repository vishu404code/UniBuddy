# UniBuddy backend

FastAPI API for UniBuddy: Neon PostgreSQL with pgvector, Cloudflare R2 for private PDFs, Gemini for
embeddings and answers, and UniBuddy's own session tokens after Google sign-in. Supabase is not used.

Setup, accounts and the first run are in [docs/SETUP.md](docs/SETUP.md). The Google login contract for
the frontend is in [docs/GOOGLE_LOGIN_CONTRACT.md](docs/GOOGLE_LOGIN_CONTRACT.md).

## What the backend does

- **Sign-in:** `POST /api/v1/auth/google` verifies a Google ID token and returns a UniBuddy session token.
  Roles come only from the `profiles` table. Access requests from new people wait for approval.
- **Documents:** upload (202), processing in a worker (text extraction, page-aware chunks, Gemini
  embeddings), publish, archive. PDFs are stored privately in R2 under `<campus>/<document>.pdf`.
- **Chat:** answers come only from published documents, with source and page citations. Without evidence
  it abstains. If Gemini fails, the question is kept and can be sent to faculty.
- **Tickets, announcements, notifications, dashboards:** role-scoped, with row rules in the database.
- **Provisioning:** Authority invites Students and Faculty. Super Admin provisions Authority and
  Management. The client never sends a role, campus or owner.

## Layout

```
app/
  auth/            Google token checks, session tokens, linking rules
  db/bootstrap/    roles and the user helper (run once, before the migrations)
  db/migrations/   the schema, row rules, and RPCs (the source of truth)
  services/        business logic; postgres_client.py is the data access layer
  storage/         R2 adapter and the in-memory test store
  ai/              Gemini client and RAG rules
tools/first_run.py schema and one-time Authority bootstrap (owner only)
tests/           backend tests; tests/sql/ holds SQL assertions run on a local database
```

## Settings

`app/config.py` lists every setting. `.env.example` lists them all with placeholders. Secrets are
read from the environment only: `DATABASE_URL`, `SESSION_SECRET`, `R2_*`, `GEMINI_API_KEY`.

## Run the tests

From `backend/`:

```bash
.venv/bin/python -m pytest -q                       # no database needed; DB tests are skipped
```

With a local PostgreSQL 17 server (with pgvector), the database tests run too:

```bash
PGPORT=54329 PGUSER_LOCAL=<your-local-user> tests/sql/run_db_tests.sh      # rebuilds unibuddy_portable, runs SQL assertions
TEST_DATABASE_URL=postgresql://<your-local-user>@localhost:54329/unibuddy_portable \
TEST_ACCESS_DATABASE_URL=postgresql://<your-local-user>@localhost:54329/unibuddy_stage1 \
  .venv/bin/python -m pytest -q
TEST_DATABASE_URL=postgresql://<your-local-user>@localhost:54329/postgres \
  .venv/bin/python -m pytest -q tests/test_first_run.py   # creates and drops unibuddy_first_run_test
```

The R2 adapter is tested with botocore's Stubber, not a real bucket. The Gemini client is tested with a
fake SDK object. Nothing in the default run contacts Google, Neon, R2 or Gemini.

## Status (what is verified, and what is not)

Verified by the commands above on this machine:

- The backend test suite, the SQL assertions against a freshly built local database, and the first-run
  tests. The exact counts from the latest run are reported in the release notes, not repeated here.

Not verified:

- Live Neon, live R2, live Gemini calls with a new key, live Google sign-in, and the Render deployment.
- The frontend login. The existing frontend still uses Supabase Auth until the Google UI is connected
  (see the contract). Until then the old login screen cannot sign in against this backend.
- End-to-end document upload, processing and chat on the new database with real PDFs.

Decisions still open:

1. The owner-only `bootstrap_super_admin` SQL function still checks for the university domain.
2. `POST /auth/registrations` still accepts a typed email without Google verification. It grants nothing.
3. The session token is stored by the frontend in local storage (an httpOnly cookie is stronger).
