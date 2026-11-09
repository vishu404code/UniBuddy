# GitHub Pages UI setup

The main website is the repository-root `index.html`. GitHub Pages serves it at
`https://vishu404code.github.io/UniBuddy/`. The React app in `frontend/` is a
separate local test UI and is not used by GitHub Pages.

## Public browser settings

Edit `runtime-config.js` before publishing:

```js
window.UB_CONFIG = Object.freeze({
  apiBase: "https://YOUR-BACKEND/api/v1",
  googleClientId: "YOUR-GOOGLE-OAUTH-WEB-CLIENT-ID",
});
```

These are public browser values. Never put a database password, session secret,
Gemini key, R2 secret, or any other private key in this file.

The Google client ID must be the same value configured on the backend as
`GOOGLE_CLIENT_ID`. In Google Cloud OAuth settings, add
`https://vishu404code.github.io` as an authorized JavaScript origin. For local
preview, also add `http://127.0.0.1:8099`.

## Backend requirements

The backend URL must use HTTPS and serve the current Google/Postgres API, not
the older Supabase deployment. Its `ALLOWED_ORIGINS` must include
`https://vishu404code.github.io`. The backend also needs its private Postgres,
session, Gemini, and R2 settings configured on its host.

GitHub Pages cannot run the local `server.js` proxy. The browser calls the
backend URL directly, so `localhost` is never valid in the published settings.

## What the Pages UI currently connects

- Google sign-in and role lookup (`/auth/google`, `/auth/me`)
- Student chat and citations (`/chat/ask`)
- Tickets, ticket details, faculty reply/status, and student forwarding
- Documents list, PDF upload, publish, and archive
- Announcements, dashboard summaries, departments, and notifications

Each role comes from the backend profile. A new verified Google account is a
Student under the current backend rule. Faculty, Authority, and Management must
already have their protected account/profile provisioned. Ticket forwarding is
unavailable when the account has no campus or the campus has no departments.

These screens are wired to the API, but they are not live-verified until the
new backend and database are deployed and configured.
