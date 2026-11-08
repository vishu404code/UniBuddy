# UniBuddy frontend (React + Vite)

Authentication and role dashboards for UniBuddy. This app is separate from the friend-owned
vanilla `index.html` at the repository root, which is not changed.

## Run locally

```bash
cd frontend
npm install
cp .env.example .env.local     # then fill in the publishable key and URLs
npm run dev                    # http://localhost:5173
```

Other scripts: `npm test` (unit tests), `npm run build` (production bundle in `dist/`).

## Settings (`frontend/.env.local`)

| Name | Value | Notes |
|---|---|---|
| `VITE_SUPABASE_URL` | Project URL | Public. |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Publishable key (`sb_publishable_…`) | Public by design. Never use the secret key here. |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` in development | FastAPI base URL. |

`.env.local` is git-ignored. Before sharing a build, check its output for key-shaped values.

## Pages

| Path | Who | What it does |
|---|---|---|
| `/login` | everyone | Email and password through Supabase Auth. Then `GET /auth/me` decides the dashboard. |
| `/register` | students | Public registration request. Grants nothing. Restricted to the university domain. |
| `/accept-invitation` | invitees, reset requests | Verifies the single-use email token (`token_hash`), then goes to `/set-password`. |
| `/set-password` | invitees, reset requests | The user chooses their own password (at least 12 characters). |
| `/forgot-password` | everyone | Sends a reset email. The same message is shown whether or not the address has an account. |
| `/student/dashboard` | student | `GET /dashboard/student` |
| `/faculty/dashboard` | faculty | `GET /dashboard/staff` |
| `/authority/dashboard` | authority | `GET /dashboard/staff` |
| `/management/dashboard` | management | `GET /management/stats`: aggregates only |
| `/authority/invitations` | authority | Invite students and faculty to the authority's campus; approve or reject pending registrations |
| `/super-admin/accounts` | Super Admin | Invite authority and management accounts; list accounts (account fields only) |

## How the connection works

1. Sign-in and password changes go directly to Supabase Auth with the publishable key.
   The session token is then sent to FastAPI as `Authorization: Bearer …`.
2. FastAPI verifies that token against Supabase's public signing keys and loads the role and
   campus from the `profiles` table. The browser never supplies its role or campus.
3. Each dashboard calls one protected endpoint. The UI route check is only a convenience.
   FastAPI and Supabase RLS enforce the same roles on every request.

## Security notes

- No secret key, OpenAI key or service-role value appears anywhere in this app.
- Tokens are held by the Supabase client in the browser's session storage. This is the
  standard Supabase pattern. A strict Content Security Policy is a later hardening step.
- The domain and password checks in the UI are for convenience only. The server enforces
  them again.
