# UniBuddy Backend

FastAPI backend for UniBuddy. This is Milestone 1: app foundation + health
endpoint only. No database, auth, or AI integration yet — those come in
later milestones.

## Setup

From the `backend/` directory:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy the environment template and adjust if needed (defaults work for local dev):

```bash
cp .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload
```

The API is now at `http://localhost:8000`. Interactive docs (Swagger UI):
`http://localhost:8000/docs`.

Check the health endpoint:

```bash
curl http://localhost:8000/api/v1/health
```

Expected response:

```json
{"status": "ok", "app": "UniBuddy Backend", "env": "development"}
```

## Test

```bash
pytest
```

Expected: 1 test passes (`test_health_check_returns_ok`).

## Database (Supabase) — Milestone 2

Schema lives in `supabase/migrations/` as plain numbered SQL files (Supabase
CLI naming convention). **Nothing in this repo has been run against a live
database** — these are reviewed, not executed, since no DB connection has
been configured/authorized yet.

Tables: `campuses`, `departments`, `profiles` (roles: student/faculty/
authority/management), `documents` + `document_chunks` (pgvector,
1536-dim), `conversations` + `messages`, `tickets` + `ticket_events`,
`announcements`, `notifications`. Every table has row-level security
enabled; see comments in each migration file for the reasoning.

**What's needed in the Supabase dashboard, when you're ready to apply this:**

1. If you don't already have one: create a Supabase project (Dashboard →
   New Project). Pick a region, set a DB password — keep that password
   yourself, never share it in chat.
2. pgvector doesn't need manual enabling — migration `20261108120000_extensions.sql`
   runs `create extension if not exists vector;` itself. (You can verify
   it's available under Database → Extensions → "vector" after applying.)
3. From Project Settings → API, you'll eventually need `Project URL` and
   the `service_role` key for the backend's `.env` (not `.env.example`,
   never shared in chat). Not required for this milestone — only once we
   wire the backend up to Supabase.

**To actually apply these migrations** (only once you've decided to and
have a project/connection ready), either:

- Supabase CLI: `supabase link --project-ref <your-ref>` then
  `supabase db push` from `backend/`, or
- Manually: open the SQL Editor in the Supabase dashboard and run each file
  in `supabase/migrations/` in filename order.

Tell me explicitly when you want this run against a real database and how
(local Postgres for testing, or your actual Supabase project) — I won't run
it on my own.

## Project layout

```
backend/
  app/
    main.py      FastAPI app instance, CORS, routes
    config.py    Settings loaded from environment variables / .env
  tests/
    test_health.py
  requirements.txt
  .env.example
  pytest.ini
```
