"""Decides what a Google sign-in may do. Pure rules, no database access.

- A Google identity matches a profile by its Google subject, or by an exact verified
  email on a profile that has no Google subject yet.
- A profile already linked to a different Google subject is never reassigned.
- No match means the person may only request Student access. They get no role.
- Roles are never read from Google, and a request never carries a role.
"""

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.auth.google_identity import GoogleIdentity

REQUESTABLE_ROLE = "student"


class SignInOutcome(str, Enum):
    SIGN_IN = "sign_in"  # profile already linked to this Google subject
    LINK = "link"  # profile matched by verified email; link this subject to it
    CONFLICT = "conflict"  # email or subject matches a conflicting profile; refuse
    NO_PROFILE = "no_profile"  # no UniBuddy account yet; may request Student access


@dataclass(frozen=True)
class ProfileRecord:
    id: UUID
    email: str
    google_subject: str | None


@dataclass(frozen=True)
class SignInDecision:
    outcome: SignInOutcome
    profile_id: UUID | None = None


def decide_sign_in(identity: GoogleIdentity, profiles: list[ProfileRecord]) -> SignInDecision:
    email = identity.email.strip().lower()

    linked = [p for p in profiles if p.google_subject == identity.subject]
    if len(linked) > 1:
        return SignInDecision(SignInOutcome.CONFLICT)
    if linked:
        return SignInDecision(SignInOutcome.SIGN_IN, linked[0].id)

    by_email = [p for p in profiles if p.email.strip().lower() == email]
    if len(by_email) > 1:
        return SignInDecision(SignInOutcome.CONFLICT)
    if by_email:
        match = by_email[0]
        if match.google_subject is None:
            return SignInDecision(SignInOutcome.LINK, match.id)
        # Same email, but the profile belongs to another Google subject.
        return SignInDecision(SignInOutcome.CONFLICT)

    return SignInDecision(SignInOutcome.NO_PROFILE)


def build_student_request(identity: GoogleIdentity, pending_subjects: set[str]) -> dict[str, str]:
    """Returns the row for a pending Student request. Idempotent per Google subject.

    The row never includes a role other than the one allowed for requests, and the
    caller must not accept a role from the person.
    """
    if identity.subject in pending_subjects:
        raise ValueError("a pending request already exists for this Google account")
    return {
        "google_subject": identity.subject,
        "email": identity.email,
        "full_name": identity.full_name or "",
        "requested_role": REQUESTABLE_ROLE,
        "status": "pending",
    }
