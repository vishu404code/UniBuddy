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
| `VITE_GOOGLE_CLIENT_ID` | Google OAuth client ID | Public. The client secret is never used in the frontend. |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` in development | FastAPI base URL. |

`.env.local` is git-ignored. Before sharing a build, check its output for key-shaped values.

## Pages

| Path | Who | What it does |
|---|---|---|
| `/login` | everyone | Sign in with Google. The API matches the Google identity to an existing account, and `GET /auth/me` decides the dashboard. |
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
| `/student/chat` | student | Ask UniBuddy. Answers show their source and page. If the documents do not answer, send the question to faculty. |
| `/student/tickets`, `/student/tickets/:id` | student | Track your tickets and faculty replies. |
| `/faculty/documents`, `/authority/documents` | faculty, authority | Upload an official PDF, watch processing, publish when ready, archive. |
| `/faculty/tickets`, `/authority/tickets` (+ `/:id`) | faculty, authority | Assigned, unassigned and campus-queue tickets. Take a ticket, reply, change status. |

## How the connection works

1. Google Identity Services shows the sign-in button and returns a Google ID token. The browser sends it
   once to `POST /auth/google`, which returns UniBuddy's session token. Later requests send that token as
   `Authorization: Bearer …`.
2. FastAPI verifies UniBuddy's session token and loads the role and
   campus from the `profiles` table. The browser never supplies its role or campus.
3. Each dashboard calls one protected endpoint. The UI route check is only a convenience.
   FastAPI and the database rules enforce the same roles on every request.

## Security notes

- No secret key, OpenAI key or service-role value appears anywhere in this app.
- UniBuddy's session token is kept in this browser's local storage. It is a convenience for
  returning users, and it can be read by script in this page. A strict Content Security Policy and an
  httpOnly cookie are later hardening steps.
- The domain and password checks in the UI are for convenience only. The server enforces
  them again.
