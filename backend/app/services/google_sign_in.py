"""Google sign-in and sign-up for UniBuddy.

Google verifies the person and the email. The UniBuddy profile, found by the account's ID,
decides access. A new Google account gets no access until an authorized person approves
a Student request. Faculty, Authority and Management are provisioned only by an authorized
invitation.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.auth.google_identity import GoogleAuthError, GoogleIdentity, verify_google_id_token
from app.auth.linking import ProfileRecord, SignInOutcome, decide_sign_in
from app.auth.session import issue_session_token
from app.schemas.registration import RegistrationRequestIn
from app.services.registrations import submit_registration

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


async def sign_in(*, sb, id_token: str, client_id: str | None, session_secret: str | None,
                  verifier: Verifier | None = None) -> dict[str, Any]:
    identity = _verify(id_token, client_id, verifier)
    if not session_secret:
        raise GoogleSignInError(503, "not_configured", "Sign-in is not configured")

    decision = decide_sign_in(identity, await _candidates(sb, identity))
    if decision.outcome is SignInOutcome.CONFLICT:
        raise GoogleSignInError(409, "conflict", "This email is linked to a different Google account")
    if decision.outcome is SignInOutcome.NO_PROFILE or decision.profile_id is None:
        raise GoogleSignInError(403, "no_profile", "Your account is not set up yet. Request access or contact your campus office.")

    profile_id = decision.profile_id
    profiles = await sb.select_service("profiles", {"select": "id", "id": f"eq.{profile_id}"})
    if not profiles:
        # An account row without a profile grants nothing.
        raise GoogleSignInError(403, "no_profile", "Your account is not set up yet. Contact your campus office.")

    if decision.outcome is SignInOutcome.LINK:
        linked = await sb.update_service(
            "account_identities",
            {"id": f"eq.{profile_id}", "google_subject": "is.null"},
            {"google_subject": identity.subject},
        )
        if not linked:
            raise GoogleSignInError(409, "conflict", "This account was linked just now. Try signing in again.")

    token = issue_session_token(profile_id, session_secret)
    return {"access_token": token, "token_type": "bearer"}


async def request_student_access(*, sb, id_token: str, client_id: str | None,
                                 verifier: Verifier | None = None) -> dict[str, Any]:
    """Files a pending Student request for a Google-verified person. Grants nothing.

    A person who already has a profile gets a plain answer and no new request.
    """
    identity = _verify(id_token, client_id, verifier)
    decision = decide_sign_in(identity, await _candidates(sb, identity))
    if decision.outcome in (SignInOutcome.SIGN_IN, SignInOutcome.LINK):
        return {"status": "has_account", "message": "You already have a UniBuddy account. Sign in instead."}
    if decision.outcome is SignInOutcome.CONFLICT:
        raise GoogleSignInError(409, "conflict", "This email is linked to a different Google account")

    return await submit_registration(
        sb=sb,
        body=RegistrationRequestIn(email=identity.email, full_name=identity.full_name or identity.email),
    )
