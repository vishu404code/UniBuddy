# Google login: API contract for the frontend

The browser sends a Google ID token once. The backend verifies it, creates or finds the UniBuddy account,
and returns UniBuddy's own session token. The role comes only from the backend's profile record.
Nothing here is a secret. The client secret is never used by the frontend.

## What the browser sends

1. Google Identity Services shows Google's button, using the public client ID (set in the page configuration).
2. Google returns an ID token (a credential string) to the page.
3. The page sends that credential, and nothing else, to the backend as `{ "id_token": "<credential>" }`.

The browser must never send a role, campus, department, email or account ID. The backend rejects unknown fields with 422.

## Endpoints

### `POST /api/v1/auth/google`

Request body: `{ "id_token": "<Google credential>" }`

| Status | Body | Meaning |
|---|---|---|
| 200 | `{ "access_token": "...", "token_type": "bearer" }` | Signed in. Send `access_token` as `Authorization: Bearer <token>`. |
| 401 | `{ "detail": { "code": "google_unverified", "message": "..." } }` | The token is invalid, expired, not for this app, or the Google email is not verified. |
| 409 | `{ "detail": { "code": "conflict", "message": "..." } }` | The email is linked to a different Google account, or the account was linked at the same moment. |
| 422 | validation error | Extra or malformed fields. |
| 503 | `{ "detail": { "code": "not_configured", "message": "..." } }` | The server has no Google client ID or session secret. |
| 503 | `{ "detail": { "code": "signup_failed", "message": "..." } }` | The Student account could not be created. Try again. |

A verified person with no account gets a **Student** account on this call. A 200 is returned with a token.

### `GET /api/v1/auth/me`

Requires `Authorization: Bearer <access_token>`. Returns:

```json
{ "id": "...", "email": "...", "full_name": "...", "role": "student", "campus_id": null,
  "department_id": null, "cross_campus_record_access": false }
```

Use `role` from this response to choose the dashboard. Errors:

- 401 for an invalid or expired token.
- 403 `"No UniBuddy profile exists for this account"` if the token is valid but no profile exists (for example, a deleted profile).

### `POST /api/v1/auth/google/access-request`

Request body: the same `{ "id_token": "<Google credential>" }`.
This creates the Student account if it does not exist yet, and never creates a pending row.

| Status | Body | Meaning |
|---|---|---|
| 202 | `{ "status": "has_account", "message": "..." }` | The Student account exists or was created. Sign in to continue. |
| 401 / 409 / 503 | as above | As above. |

## Rules the backend enforces

- **Any verified email domain** may sign in. Google must report the email as verified.
- **Open Student signup.** A verified person with no account becomes a Student with no campus and no department.
- **Privileged roles are never created by sign-in.** Faculty, Authority and Management come only from authorized
  provisioning. The Student signup function can create nothing else.
- **Roles come only from the profile.** Never from the token, from Google, from an email address, or from the browser.
- **Linking.** An account invited by email is linked to the Google account the first time that verified email signs in.
  The profile ID does not change. An email linked to another Google account is refused (409).
- **Session.** The token is UniBuddy's own, signed by the server, valid for 8 hours. It holds only the user ID and timing.

## Suggested page behaviour

- On 200: store the token, call `GET /auth/me`, and go to the dashboard for `role`.
- On 401: ask the person to sign in again. Google credentials expire after about an hour.
- On 409: show a generic message and ask them to contact the campus office.
- Never show raw server error text to the person.
- Do not call `POST /api/v1/auth/registrations`. It is an older, unverified endpoint and is not part of this flow.

## Backend settings this contract needs (server side only)

| Setting | Value | Where |
|---|---|---|
| `GOOGLE_CLIENT_ID` | the public OAuth Web client ID (the same one the page uses) | backend private settings |
| `SESSION_SECRET` | 32+ random characters | backend private settings only |
| `DATABASE_URL` | Neon connection string (app role) | backend private settings only |
| `ALLOWED_ORIGINS` | must include the exact frontend origin, for example `https://vishu404code.github.io` | backend private settings |

## What is not tested here

The backend tests use an injected Google verifier and a local database. They do not contact Google.
A real Google round trip with a real account has not been tested. Test it before relying on it.
