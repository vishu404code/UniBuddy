# Setup: one checklist for the owner

Everything below is done by you, in your own accounts. Never paste a secret into chat, into frontend
code, or into Git. Put secrets only in `backend/.env` on your machine, and in the Render dashboard
for the hosted service. Free plans only. Check each provider's current free limits before you rely on them.

## 1. Neon (database)

1. Sign in at https://neon.com and create a project (free plan). Choose the region closest to you.
2. Enable the `vector` extension: the migrations run `create extension vector`, so no manual step is
   needed if your role can create extensions. If that is refused, run `create extension vector;` once
   in the Neon SQL editor as the project owner.
3. Copy the **owner** connection string. Use it only for the first-run setup below, as `OWNER_DATABASE_URL`.
4. Create a second, non-superuser role for the app (Neon's role page or SQL editor). Grant it the roles
   from `app/db/bootstrap`, then copy its connection string as `DATABASE_URL`:
   `grant anon, authenticated, service_role to <app-role>;` (after the bootstrap has created them).
   Superusers and owners bypass row rules, so the app must not connect as the owner.

## 2. Cloudflare R2 (private PDF storage)

1. Sign in at https://dash.cloudflare.com and open **R2 object storage**. Check that the free plan
   covers your use before you create anything.
2. Create a bucket named `unibuddy-documents`. Keep it **private** (no public access).
3. Create an **R2 API token** with Object Read & Write on that bucket only.
4. Copy the account ID, access key ID and secret access key into `backend/.env` as `R2_ACCOUNT_ID`,
   `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY`.

For a laptop-only demo before R2 is configured, set `STORAGE_BACKEND=local` and
`LOCAL_STORAGE_DIR=.local-data/objects` in `backend/.env`. This stores uploaded PDFs on that Mac only;
do not use local storage on Render or for a shared/production app.

## 3. Google Cloud (sign-in). Your friend builds the UI; you create the client.

1. Open https://console.cloud.google.com, create a project, and go to **APIs & Services → OAuth consent
   screen**. Choose **External**, fill in the app name and your support email, and add the scopes
   `openid`, `email` and `profile`.
2. Go to **Credentials → Create credentials → OAuth client ID → Web application**.
3. Under **Authorized JavaScript origins**, add `http://localhost:5173` (and your hosted frontend URL later).
4. Copy the **Client ID** into `backend/.env` as `GOOGLE_CLIENT_ID`, and give the same Client ID to your
   friend for `VITE_GOOGLE_CLIENT_ID`. Do not give out or store the client secret; the sign-in flow does not need it.
5. While the app is in **Testing** mode, add each test Google account under **Test users**.

## 4. Local settings (`backend/.env`)

Copy `backend/.env.example` to `backend/.env` and fill in:

- `DATABASE_URL` (Neon app role), `SESSION_SECRET` (generate 32+ random characters, for example with
  `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`), `GOOGLE_CLIENT_ID`
- `R2_*` (from step 2), `GEMINI_API_KEY` (from Google AI Studio)

Remove any old `SUPABASE_*` lines. The backend no longer reads them.

## 5. First run on the empty database (owner, once)

From `backend/`, with `OWNER_DATABASE_URL` set to the Neon **owner** string (run in your own terminal;
do not paste it into chat):

```bash
OWNER_DATABASE_URL='<owner connection string>' .venv/bin/python tools/first_run.py schema --confirm
OWNER_DATABASE_URL='<owner connection string>' .venv/bin/python tools/first_run.py authority \
  --campus-name "Rishihood University, Sonipat" --campus-code sonipat \
  --email "<your email>" --full-name "<your name>" --confirm
```

- The schema step refuses a database that already has tables.
- The Authority step refuses if an Authority already exists, so it runs once.
- Use the campus name and code you want. The campus is created once and then reused.

## 6. Start the services

```bash
cd backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010   # the API
.venv/bin/python -m app.worker                                 # optional, separate worker
```

The document worker also runs inside the API when `DOCUMENT_WORKER_ENABLED=true`.

## 7. Log in and test each role

Everyone signs in with the Google account whose verified email matches their UniBuddy record.

- **Authority (you):** sign in with the email you used in step 5. Open the Documents page, upload the
  Leave of Absence PDF with scope **university-wide**, wait for **Ready**, then **Publish**.
- **Faculty and Student:** an Authority adds them with the invitation page, which creates their record
  for that email. A Student may also request access with Google, and waits for Authority approval.
  Faculty never get access by requesting it.
- **Your friend's UI:** must connect to `docs/GOOGLE_LOGIN_CONTRACT.md` before any of these steps work.
  Until then the existing login screen cannot sign in against this backend.

## 8. Render (hosted API), when you are ready

1. Create a **free** Web Service from this repo, branch that you choose for the backend (the code
   must be on it first), root directory `backend`. Pick the region closest to Neon (AWS us-east-2 / Ohio).
2. Build command: `pip install -r requirements.txt`. Start command:
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Environment variables (private, set in the Render dashboard only):
   - `APP_ENV=production` (this also refuses local file storage, so PDFs cannot sit on Render's temporary disk)
   - `STORAGE_BACKEND=r2`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` (the bucket name)
   - `DATABASE_URL` (Neon app role, **hostname form only**: do not add `hostaddr`)
   - `SESSION_SECRET`, `GOOGLE_CLIENT_ID`, `GEMINI_API_KEY`
   - `ALLOWED_ORIGINS=https://vishu404code.github.io`
   - Do not add any `SUPABASE_*` variable, and do not set `OWNER_DATABASE_URL` on Render.
4. Before pushing a new commit, check **Auto-Deploy** for this service. If it is on, a push redeploys
   the service, so push only when the new code has been tested.
5. Free Render services sleep when idle, so the first request after a pause can take a minute.

## 9. Retiring the old Supabase project

Only after the new system works end to end, and only you may do it: open the project
`unibuddy-dev-mumbai-2` (`xbpbnzcfnrcljjfuwhhy`) in the Supabase dashboard, pause or delete it, and
confirm the step there with your own login. Do not touch any other Supabase project.
