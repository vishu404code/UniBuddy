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
  "campus_id": "…", "department_id": "…", "all_campuses_access": false
}
```

How the backend identifies the caller:

1. The token signature is checked against Supabase's public signing keys, from
   `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`. Only ES256 and RS256 are
   accepted. HS256 and `alg: none` are rejected.
2. The audience must be `authenticated`, the issuer `<SUPABASE_URL>/auth/v1`,
   and `exp`, `iat` and `sub` must be present.
3. `sub` is looked up in `profiles` with the service-role key. Role, campus,
   department and `all_campuses_access` come from that row. Token claims such as
   `user_metadata` are never used for authorization.
4. A valid token with no profile row gets `403`.

FastAPI dependencies live in `app/middleware/auth.py`: `get_current_user` and
`require_roles("faculty", ...)`.

### Access rules (working defaults)

| Data | Rule |
|---|---|
| Public student-facing documents | Every authenticated student across all campuses. Not filtered by campus. |
| Tickets | Student sees their own. Assigned faculty sees assigned tickets. Faculty sees their campus and department queue. Authority sees its own campus. Management sees all campuses only with `all_campuses_access`. |
| Profiles | Own profile. Faculty and authority see their own campus. Management sees all campuses only with `all_campuses_access`. |
| `all_campuses_access` | Set by the backend, allowed only for `management`. Never set at signup. |

Management has no cross-campus access unless `all_campuses_access` is true.
Those are the default rules. The next section lists rules still open.

## Supabase development project setup

Use a separate development project. Do not use a production project for this.

1. **Create the project.** Sign in at supabase.com, then choose New project.
   Name it something like `unibuddy-dev`. Pick the region closest to your campuses.
   Set a database password and store it in a password manager. This backend does not
   need the password yet.
2. **Copy the Project URL.** In the project, go to Project Settings → API. Copy
   *Project URL*. It looks like `https://<project-ref>.supabase.co`.
3. **Copy the service-role key.** On the same page, find the *service_role*
   key and reveal it. It is secret and bypasses row-level security. Only put
   it in your local `backend/.env`.
4. **Check the JWT signing keys.** Go to Project Settings → JWT Keys. Labels vary by
   dashboard version, so look for *JWT Signing Keys*. The backend needs an
   asymmetric key (ES256 or RS256). If the project only shows a legacy HS256
   secret, stop and tell me, because the verifier does not accept it.
5. **Fill in your local `.env`.** Open `backend/.env` in a text editor and set:
   ```
   SUPABASE_URL=https://<your-dev-project-ref>.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=<paste the service_role key here>
   ```
   Save the file. Never paste these values into chat, commit them, or add them to
   the frontend.
6. **Create test users when migrations are applied.** Go to Authentication → Users
   → Add user → Create new user. Tick *Auto Confirm User* so you can sign in without
   email verification. Copy the user's UUID.
7. **Create a test profile.** After migrations are applied, open the SQL Editor and
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

- **Staff-only documents and announcements:** currently every faculty, authority and
  management account can read them across all campuses. This does not match the
  authority campus default. Tell me who should read them.
- **Staff draft visibility:** staff currently read draft and archived documents across
  campuses too. Tell me whether drafts should be limited to their uploader and campus.

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
    repositories/profiles.py    Profile lookup via Supabase REST (service role)
    schemas/auth.py             CurrentUser model and role type
  supabase/migrations/          Schema, RLS policies, indexes (not yet applied)
  tests/                        pytest suite (30 tests)
  requirements.txt
  .env.example
  pytest.ini
```
