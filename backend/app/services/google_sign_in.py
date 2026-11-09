"""Google sign-in and sign-up for UniBuddy.

Google verifies the person and the email. The database decides access:
- A known Google account signs in to its existing profile, whatever its role.
- A verified Google person with no profile becomes a Student (open signup). A new Student gets the only existing campus when the database has exactly one;
  no department is assigned here.
- Faculty, Authority and Management are never created here. They come only from authorized provisioning.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from app.auth.google_identity import GoogleAuthError, GoogleIdentity, verify_google_id_token
from app.auth.linking import ProfileRecord, SignInOutcome, decide_sign_in
from app.auth.session import issue_session_token
from app.services.errors import DataServiceError

ACCOUNT_COLUMNS = "id,email,google_subject"
Verifier = Callable[[str, str], dict[str, Any]]


class GoogleSignInError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _verify(id_token: str, client_id: str | None, verifier: Verifier | None) -> GoogleIdentity:
    if not client_id:
        raise GoogleSignInError(503, "not_configured", "Google sign-in is not configured")
    try:
        return verify_google_id_token(id_token, client_id, verifier=verifier)
    except GoogleAuthError as exc:
        raise GoogleSignInError(401, "google_unverified", "Google sign-in could not be verified") from exc


async def _candidates(sb, identity: GoogleIdentity) -> list[ProfileRecord]:
    by_subject = await sb.select_service("account_identities", {"select": ACCOUNT_COLUMNS, "google_subject": f"eq.{identity.subject}"})
    by_email = await sb.select_service("account_identities", {"select": ACCOUNT_COLUMNS, "email": f"eq.{identity.email}"})
    seen: dict[str, ProfileRecord] = {}
    for row in [*by_subject, *by_email]:
        seen[str(row["id"])] = ProfileRecord(
            id=UUID(str(row["id"])), email=(row["email"] or "").lower(), google_subject=row["google_subject"]
        )
    return list(seen.values())


async def _create_student_profile(sb, account_id: UUID, identity: GoogleIdentity) -> None:
    try:
        await sb.rpc_service(
            "open_student_signup",
            {"p_account": str(account_id), "p_email": identity.email, "p_full_name": identity.full_name},
        )
    except DataServiceError as exc:
        raise GoogleSignInError(503, "signup_failed", "Your account could not be created. Try again.") from exc
    await _assign_existing_campus(sb, account_id)


async def _assign_existing_campus(sb, account_id: UUID) -> None:
    """A new Student gets the campus only when exactly one campus exists in the database, so no
    campus is invented or guessed. With several campuses the Student stays unassigned for an
    authorized person to place."""
    campuses = await sb.select_service("campuses", {"select": "id"})
    if len(campuses) != 1:
        return
    await sb.update_service(
        "profiles",
        {"id": f"eq.{account_id}", "role": "eq.student", "campus_id": "is.null"},
        {"campus_id": str(campuses[0]["id"])},
    )


async def _profile_exists(sb, account_id: UUID) -> bool:
    return bool(await sb.select_service("profiles", {"select": "id", "id": f"eq.{account_id}"}))


async def _resolve_account(sb, identity: GoogleIdentity, verifier_ok: bool = True) -> UUID:
    """Returns the account ID that the verified person should sign in to, creating a Student if needed."""
    decision = decide_sign_in(identity, await _candidates(sb, identity))
    if decision.outcome is SignInOutcome.CONFLICT:
        raise GoogleSignInError(409, "conflict", "This email is linked to a different Google account")

    if decision.outcome is SignInOutcome.NO_PROFILE or decision.profile_id is None:
        account_id = uuid4()
        try:
            await sb.insert_service(
                "account_identities",
                [{"id": str(account_id), "email": identity.email, "google_subject": identity.subject}],
            )
        except DataServiceError as exc:
            if exc.status_code == 409:
                raise GoogleSignInError(409, "conflict", "This Google account was just linked. Try again.") from exc
            raise GoogleSignInError(503, "signup_failed", "Your account could not be created. Try again.") from exc
        await _create_student_profile(sb, account_id, identity)
        return account_id

    account_id = decision.profile_id
    if not await _profile_exists(sb, account_id):
        await _create_student_profile(sb, account_id, identity)

    if decision.outcome is SignInOutcome.LINK:
        linked = await sb.update_service(
            "account_identities",
            {"id": f"eq.{account_id}", "google_subject": "is.null"},
            {"google_subject": identity.subject},
        )
        if not linked:
            raise GoogleSignInError(409, "conflict", "This account was linked just now. Try signing in again.")
    return account_id


async def sign_in(*, sb, id_token: str, client_id: str | None, session_secret: str | None,
                  verifier: Verifier | None = None) -> dict[str, Any]:
    identity = _verify(id_token, client_id, verifier)
    if not session_secret:
        raise GoogleSignInError(503, "not_configured", "Sign-in is not configured")
    account_id = await _resolve_account(sb, identity)
    token = issue_session_token(account_id, session_secret)
    return {"access_token": token, "token_type": "bearer"}


async def request_student_access(*, sb, id_token: str, client_id: str | None,
                                 verifier: Verifier | None = None) -> dict[str, Any]:
    """Kept for the existing contract. Creates the Student account if needed. Grants nothing privileged.

    Returns 'has_account' with a message; the person then signs in with Google.
    """
    identity = _verify(id_token, client_id, verifier)
    await _resolve_account(sb, identity)
    return {"status": "has_account", "message": "Your UniBuddy Student account is ready. Sign in to continue."}
