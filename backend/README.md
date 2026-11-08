# UniBuddy Backend

FastAPI backend for UniBuddy. Implemented so far: app foundation and health
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

Expected: 30 tests pass. The tests use a locally generated signing key and a
fake JWKS client, so they never contact Supabase.

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

## Open decisions

- **`cross_campus_record_access`:** decided, no user holds it. It stays `false` for
  everyone, and nothing in the backend sets it. Management reporting stays aggregate-only.
- **Who sets `scope`:** the uploader or publisher chooses `campus` or `university_wide`.
  Confirm whether a university-wide choice needs approval.

## Database (Supabase)

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

## Project layout

```
backend/
  app/
    main.py                     FastAPI app, CORS, router registration
    config.py                   Settings from environment variables / .env
    routes/auth.py              GET /api/v1/auth/me
    middleware/auth.py          FastAPI dependencies: get_current_user, require_roles
    services/token_verifier.py  Supabase JWT verification (JWKS, ES256/RS256)
    services/authorization.py   Campus access rule
    repositories/profiles.py    Profile lookup via Supabase REST (secret key)
    schemas/auth.py             CurrentUser model and role type
  supabase/migrations/          Schema, RLS policies, indexes (not yet applied)
  tests/                        pytest suite (30 tests)
  requirements.txt
  .env.example
  pytest.ini
```
