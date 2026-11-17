"""Google sign-in and sign-up for UniBuddy.

Google verifies the person and the email. The database decides access:
- A known Google account signs in to its existing profile, whatever its role.
- A verified Google person with no profile becomes a Student (open signup). A new Student gets the only existing campus when the database has exactly one;
  no department is assigned here.
- Faculty, Authority and Management are never created here, except for the server-side
  pre-authorized Faculty emails below. Those get a Faculty profile on first verified sign-in,
  never a Student profile first. Authority and Management still come only from authorized provisioning.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from app.auth.google_identity import GoogleAuthError, GoogleIdentity, verify_google_id_token
from app.auth.linking import ProfileRecord, SignInOutcome, decide_sign_in
from app.auth.session import issue_session_token
from app.services.errors import DataServiceError

logger = logging.getLogger("unibuddy.auth")
ACCOUNT_COLUMNS = "id,email,google_subject"
Verifier = Callable[[str, str], dict[str, Any]]

async def _get_single_campus_id(sb) -> str | None:
    cached = getattr(sb, "_cached_single_campus_id", None)
    if cached is not None:
        return cached
    campuses = await sb.select_service("campuses", {"select": "id"})
    if len(campuses) == 1:
        cid = str(campuses[0]["id"])
        try:
            sb._cached_single_campus_id = cid
        except Exception:
            pass
        return cid
    return None

# Pre-authorized roles, decided on the server. A verified Google email listed here gets that role on
# its first sign-in, before any default Student profile is created. Faculty needs a campus to see its
# campus records, so it is set by name. Management has no campus. No department is set here.
PREAUTHORIZED_ACCOUNTS: dict[str, tuple[str, str | None]] = {
    "tarun.s26366@nst.rishihood.edu.in": ("faculty", "Rishihood University, Sonipat"),
    "jaysinghf204@gmail.com": ("management", None),
}


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
    if hasattr(sb, "find_account_identities"):
        rows = await sb.find_account_identities(identity.subject, identity.email)
    else:
        by_subject, by_email = await asyncio.gather(
            sb.select_service("account_identities", {"select": ACCOUNT_COLUMNS, "google_subject": f"eq.{identity.subject}"}),
            sb.select_service("account_identities", {"select": ACCOUNT_COLUMNS, "email": f"eq.{identity.email}"}),
        )
        rows = [*by_subject, *by_email]
    seen: dict[str, ProfileRecord] = {}
    for row in rows:
        seen[str(row["id"])] = ProfileRecord(
            id=UUID(str(row["id"])), email=(row["email"] or "").lower(), google_subject=row["google_subject"]
        )
    return list(seen.values())


async def _create_profile(sb, account_id: UUID, identity: GoogleIdentity) -> None:
    """The pre-authorized check runs first, so a listed email never gets a Student profile."""
    preauthorized = PREAUTHORIZED_ACCOUNTS.get(identity.email.strip().lower())
    if preauthorized is None:
        await _create_student_profile(sb, account_id, identity)
    else:
        role, campus_name = preauthorized
        await _create_preauthorized_profile(sb, account_id, identity, role, campus_name)


async def _create_preauthorized_profile(
    sb, account_id: UUID, identity: GoogleIdentity, role: str, campus_name: str | None
) -> None:
    campus_id = None
    if campus_name is not None:
        campuses = await sb.select_service("campuses", {"select": "id", "name": f"eq.{campus_name}"})
        if len(campuses) != 1:
            raise GoogleSignInError(503, "signup_failed", "Your account could not be created. Try again.")
        campus_id = str(campuses[0]["id"])
    function = "open_preauthorized_faculty_signup" if role == "faculty" else "open_preauthorized_management_signup"
    payload = {"p_account": str(account_id), "p_email": identity.email, "p_full_name": identity.full_name}
    if role == "faculty":
        payload["p_campus"] = campus_id
    try:
        await sb.rpc_service(function, payload)
    except DataServiceError as exc:
        raise GoogleSignInError(503, "signup_failed", "Your account could not be created. Try again.") from exc


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
    """A Student gets the campus only when exactly one campus exists in the database, so no campus is
    invented or guessed. With several campuses the Student stays unassigned for an authorized person.

    The database function sets the campus only for a Student who has none. A failure here never blocks
    sign-in: the Student can still use the app, and the next sign-in tries again."""
    campus_id = await _get_single_campus_id(sb)
    if not campus_id:
        return
    try:
        await sb.rpc_service(
            "assign_campus_to_student",
            {"p_account": str(account_id), "p_campus": campus_id},
        )
    except DataServiceError:
        logger.warning("Campus could not be assigned to a new Student; sign-in continues")


async def _get_profile_and_healing_status(sb, account_id: UUID) -> tuple[dict[str, Any] | None, bool]:
    """Single query to check if profile exists and if student needs campus healing."""
    rows = await sb.select_service(
        "profiles", {"select": "id,email,full_name,role,campus_id,department_id,cross_campus_record_access", "id": f"eq.{account_id}"}
    )
    if not rows:
        return None, False
    row = rows[0]
    needs_healing = (row.get("role") == "student" and row.get("campus_id") is None)
    return row, needs_healing


async def _resolve_account_and_user(sb, identity: GoogleIdentity, verifier_ok: bool = True) -> tuple[UUID, dict[str, Any] | None]:
    """Returns (account_id, user_dict) in a single fast indexed query for existing accounts."""
    if hasattr(sb, "find_account_and_profile"):
        joined_rows = await sb.find_account_and_profile(identity.subject, identity.email)
        candidates = [
            ProfileRecord(id=UUID(str(r["id"])), email=(r["email"] or "").lower(), google_subject=r["google_subject"])
            for r in joined_rows
        ]
        profile_map = {str(r["id"]): r for r in joined_rows if r.get("role") is not None}
    else:
        candidates = await _candidates(sb, identity)
        profile_map = {}

    decision = decide_sign_in(identity, candidates)
    if decision.outcome is SignInOutcome.CONFLICT:
        raise GoogleSignInError(409, "conflict", "This email is linked to a different Google account")

    if decision.outcome is SignInOutcome.NO_PROFILE or decision.profile_id is None:
        account_id = uuid4()
        campus_id = await _get_single_campus_id(sb)
        preauthorized = PREAUTHORIZED_ACCOUNTS.get(identity.email.strip().lower())
        if preauthorized is None and hasattr(sb, "create_student_account"):
            try:
                await sb.create_student_account(
                    account_id, identity.email, identity.subject, identity.full_name, campus_id
                )
            except DataServiceError as exc:
                if exc.status_code == 409:
                    raise GoogleSignInError(409, "conflict", "This Google account was just linked. Try again.") from exc
                raise GoogleSignInError(503, "signup_failed", "Your account could not be created. Try again.") from exc
            user = {
                "id": str(account_id),
                "email": identity.email,
                "full_name": identity.full_name,
                "role": "student",
                "campus_id": str(campus_id) if campus_id else None,
                "department_id": None,
                "cross_campus_record_access": False,
            }
            return account_id, user

        try:
            await sb.insert_service(
                "account_identities",
                [{"id": str(account_id), "email": identity.email, "google_subject": identity.subject}],
            )
        except DataServiceError as exc:
            if exc.status_code == 409:
                raise GoogleSignInError(409, "conflict", "This Google account was just linked. Try again.") from exc
            raise GoogleSignInError(503, "signup_failed", "Your account could not be created. Try again.") from exc
        await _create_profile(sb, account_id, identity)
        profile_row, _ = await _get_profile_and_healing_status(sb, account_id)
        user = _format_user(profile_row) if profile_row else None
        return account_id, user

    account_id = decision.profile_id
    cached_profile = profile_map.get(str(account_id))
    if cached_profile:
        profile_row = cached_profile
        needs_healing = (profile_row.get("role") == "student" and profile_row.get("campus_id") is None)
    else:
        profile_row, needs_healing = await _get_profile_and_healing_status(sb, account_id)

    if not profile_row:
        await _create_profile(sb, account_id, identity)
        profile_row, _ = await _get_profile_and_healing_status(sb, account_id)
    elif needs_healing:
        await _assign_existing_campus(sb, account_id)
        campus_id = await _get_single_campus_id(sb)
        if campus_id:
            profile_row["campus_id"] = campus_id

    if decision.outcome is SignInOutcome.LINK:
        linked = await sb.update_service(
            "account_identities",
            {"id": f"eq.{account_id}", "google_subject": "is.null"},
            {"google_subject": identity.subject},
        )
        if not linked:
            raise GoogleSignInError(409, "conflict", "This account was linked just now. Try signing in again.")
    return account_id, _format_user(profile_row) if profile_row else None


def _format_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "full_name": row.get("full_name"),
        "role": row["role"],
        "campus_id": str(row["campus_id"]) if row.get("campus_id") else None,
        "department_id": str(row["department_id"]) if row.get("department_id") else None,
        "cross_campus_record_access": bool(row.get("cross_campus_record_access", False)),
    }


async def _resolve_account(sb, identity: GoogleIdentity, verifier_ok: bool = True) -> UUID:
    account_id, _ = await _resolve_account_and_user(sb, identity, verifier_ok=verifier_ok)
    return account_id


async def sign_in(*, sb, id_token: str, client_id: str | None, session_secret: str | None,
                  verifier: Verifier | None = None) -> dict[str, Any]:
    identity = await asyncio.to_thread(_verify, id_token, client_id, verifier)
    if not session_secret:
        raise GoogleSignInError(503, "not_configured", "Sign-in is not configured")
    account_id, user = await _resolve_account_and_user(sb, identity)
    token = issue_session_token(account_id, session_secret)
    out = {"access_token": token, "token_type": "bearer"}
    if user:
        out["user"] = user
    return out


async def request_student_access(*, sb, id_token: str, client_id: str | None,
                                 verifier: Verifier | None = None) -> dict[str, Any]:
    """Kept for the existing contract. Creates the Student account if needed. Grants nothing privileged.

    Returns 'has_account' with a message; the person then signs in with Google.
    """
    identity = await asyncio.to_thread(_verify, id_token, client_id, verifier)
    await _resolve_account(sb, identity)
    return {"status": "has_account", "message": "Your UniBuddy Student account is ready. Sign in to continue."}
