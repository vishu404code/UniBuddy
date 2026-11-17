# Google login: API contract for the frontend

This is the contract the Google login UI must use. The UI is owned by the frontend developer. The
backend does not build or change any login screen. Nothing here is a secret.

## What the browser sends

1. The browser loads Google Identity Services and renders Google's sign-in button, using the
   **public** OAuth client ID (`VITE_GOOGLE_CLIENT_ID`). The client secret is never used in the browser.
2. Google returns an **ID token** (a credential string) to the page.
3. The page sends that credential, and nothing else, to the backend.

The browser must never send a role, campus, department, email, or account ID. The backend rejects
unknown fields with 422.

## Endpoints

### `POST /api/v1/auth/google`

Request body:

```json
{ "id_token": "<Google credential>" }
```

| Status | Body | Meaning |
|---|---|---|
| 200 | `{ "access_token": "...", "token_type": "bearer" }` | Signed in. Send `access_token` as `Authorization: Bearer <token>`. |
| 401 | `{ "detail": { "code": "google_unverified", "message": "..." } }` | The token is invalid, expired, not for this app, or the Google email is not verified. |
| 403 | `{ "detail": { "code": "no_profile", "message": "..." } }` | Google identity is valid, but there is no UniBuddy account yet. No token is returned. Offer the access request below. |
| 409 | `{ "detail": { "code": "conflict", "message": "..." } }` | The email is linked to a different Google account. Show a generic message and contact the campus office. |
| 422 | validation error | The body had extra fields or was malformed. |
| 503 | `{ "detail": { "code": "not_configured", ... } }` | The server is not configured for Google sign-in. |

### `GET /api/v1/auth/me`

With `Authorization: Bearer <access_token>`. Returns the signed-in person's profile:

```json
{ "id": "...", "email": "...", "full_name": "...", "role": "student", "campus_id": "...",
  "department_id": null, "cross_campus_record_access": false }
```

Use `role` from this response to choose the dashboard. The role is read from the profile in the
database. It is never read from the token, from Google, or from the browser.

### `POST /api/v1/auth/google/access-request`

Request body: the same `{ "id_token": "<Google credential>" }`.

| Status | Body | Meaning |
|---|---|---|
| 202 | `{ "status": "received", "message": "..." }` | A pending Student request was filed. It grants no access. |
| 202 | `{ "status": "has_account", "message": "..." }` | The person already has an account. Send them to sign in. |
| 401 / 409 / 503 | as above | As above. |

Requests are not duplicated. Approval happens later, by an authorized person.

## Rules the backend enforces

- **Any verified email domain** may sign in or request access. Google must report the email as verified.
- **No profile, no access.** A verified identity without a profile gets no token.
- **Roles come only from the profile.** Faculty, Authority and Management accounts are created only by
  an authorized invitation. A Student is created only when an authorized person approves a request.
- **Linking.** A profile invited by email is linked to the Google account the first time that verified
  email signs in. The profile ID does not change. An email linked to another Google account is refused.
- **Session.** The access token is UniBuddy's own, signed by the server, valid for 8 hours. It contains
  only the user ID and timing. It holds no role, campus or email.

## Suggested page behaviour (for the frontend developer)

- On 200: store the token, call `GET /auth/me`, and go to the dashboard for `role`.
- On 403 `no_profile`: show "Your account is not set up yet" and offer "Request Student access", which
  calls `POST /auth/google/access-request` with the same credential, if it is still fresh.
- On 401: ask the person to sign in again. Google credentials expire after about an hour.
- Never show the raw error text from the server to the person.

## Backend settings this contract needs (server side only)

| Setting | Value | Where |
|---|---|---|
| `AUTH_BACKEND` | `google` | backend private settings |
| `DATA_BACKEND` | `postgres` | backend private settings |
| `GOOGLE_CLIENT_ID` | the same public client ID as the frontend | backend private settings |
| `SESSION_SECRET` | 32+ random characters | backend private settings only |
| `DATABASE_URL` | Neon connection string | backend private settings only |

## What is not tested here

The backend tests use an injected Google verifier and a fake database. They do not contact Google.
The real Google round trip, with a real account, has not been tested. Test it with a real account
before relying on it.
