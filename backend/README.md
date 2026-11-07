# UniBuddy Backend

FastAPI backend for UniBuddy. Implemented so far: the app foundation and health
endpoint, the Supabase schema (migrations, not yet applied), and Supabase token
verification with server-side role and campus authorization. Document upload,
RAG, chat and tickets come in later milestones.

## Setup

From the `backend/` directory:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy the environment template:

```bash
cp .env.example .env
```

`.env` is git-ignored. Fill in the Supabase values described below. Leave them
as they are if you only want the health endpoint and tests.

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

Expected: 29 tests pass. The tests use a locally generated signing key and a
fake JWKS client, so they never contact Supabase.

## Authentication and authorization

Every protected request carries `Authorization: Bearer <access token>`, where
the token is the one Supabase Auth issues to the logged-in user.

`GET /api/v1/auth/me` returns the caller's profile:

```json
{
  "id": "…", "email": "…", "full_name": "…", "role": "faculty",
  "campus_id": "…", "department_id": "…"
}
```

How the backend decides who the caller is:

1. The token's signature is checked against Supabase's public signing keys,
   fetched from `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`. Only ES256 and
   RS256 are accepted. HS256 and `alg: none` are rejected.
2. The audience must be `authenticated`, the issuer must be
   `<SUPABASE_URL>/auth/v1`, and `exp`, `iat`, `sub` must be present.
3. The `sub` claim is looked up in the `profiles` table using the service-role
   key. The role, campus and department come from that row. Token claims such
   as `user_metadata` are never used for authorization.
4. A valid token with no profile row gets `403`.

Reusable FastAPI dependencies live in `app/middleware/auth.py`:
`get_current_user` and `require_roles("faculty", ...)`. Campus scoping for
ticket-style resources is `can_access_campus` in `app/services/authorization.py`.
Management can see every campus. Other roles see only their own campus.

Status codes: `401` for a missing, malformed or untrusted token; `403` for a
valid token whose role or profile does not allow the action; `503` when
Supabase cannot be reached or auth is not configured.

## Supabase setup for authentication

Do these steps yourself. Never paste keys into chat.

1. **Create or open the project.** Supabase Dashboard → New project (or your
   existing project).
2. **Copy the Project URL.** Project Settings → API → *Project URL*. Put it in
   `backend/.env` as `SUPABASE_URL=`.
3. **Copy the service-role key.** Project Settings → API → *service_role*
   (use the reveal button). Put it in `backend/.env` as
   `SUPABASE_SERVICE_ROLE_KEY=`. Never commit it, and never put it in the
   frontend.
4. **Check the signing keys.** Project Settings → JWT Keys (sometimes labelled
   "JWT Signing Keys"). The backend needs an asymmetric key (ES256 or RS256).
   If your project only offers a legacy HS256 JWT secret, stop and tell me.
   The verifier does not accept HS256.
5. **Apply the migrations first.** `/auth/me` reads the `profiles` table, which
   only exists after the Milestone 2 migrations are applied. That step is still
   waiting for your go-ahead.
6. **Create a test user.** Authentication → Users → Add user, with an email and
   password you choose. Copy the user's UUID.
7. **Create its profile.** In the SQL Editor, after the migrations are applied,
   run this with your own values (not real credentials):

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

Then sign in as that user from your frontend, or get a token another way, and
call `GET /api/v1/auth/me` with the Bearer token. You should see the profile.

Open decisions that affect this code:
- Authority is currently limited to its own campus in `can_access_campus`. Management
  sees all campuses. If authority should also see all campuses, that is a one-line change.
- Faculty see tickets assigned to them and unassigned-or-assigned tickets in their own
  campus and department. Confirm this matches how your queues should work.

## Database (Supabase)

Schema lives in `supabase/migrations/` as numbered SQL files. They have been
parsed with PostgreSQL's grammar but **not applied to any database**. Row-level
security policies are reviewed, not yet exercised against a live database.

Tables: `campuses`, `departments`, `profiles` (roles: student, faculty,
authority, management), `documents` and `document_chunks` (pgvector, 1536
dimensions), `conversations` and `messages`, `tickets` and `ticket_events`,
`announcements`, `notifications`.

To apply them, when you choose to:

- Supabase CLI: `supabase link --project-ref <your-ref>`, then
  `supabase db push` from `backend/`, or
- SQL Editor: run each file in `supabase/migrations/` in filename order.

pgvector is enabled by the first migration (`create extension if not exists vector`).

## Project layout

```
backend/
  app/
    main.py                  FastAPI app, CORS, router registration
    config.py                Settings from environment variables / .env
    routes/auth.py           GET /api/v1/auth/me
    middleware/auth.py       FastAPI dependencies: get_current_user, require_roles
    services/token_verifier.py  Supabase JWT verification (JWKS, ES256/RS256)
    services/authorization.py   Campus access rule
    repositories/profiles.py    Profile lookup via Supabase REST (service role)
    schemas/auth.py          CurrentUser model and role type
  supabase/migrations/       Schema, RLS policies, indexes (not yet applied)
  tests/                     pytest suite (29 tests)
  requirements.txt
  .env.example
  pytest.ini
```
