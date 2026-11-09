"""Google ID-token verification.

Google proves who the person is and that the email is theirs. It never decides a
UniBuddy role, campus or department. Those come only from UniBuddy's own records.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})

Verifier = Callable[[str, str], dict[str, Any]]


class GoogleAuthError(Exception):
    """The token is missing, invalid, expired, for another app, or lacks a verified email."""


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    full_name: str | None


def _default_verifier(token: str, client_id: str) -> dict[str, Any]:
    # Checks the signature, the expiry, the issuer and that the token is for this client ID.
    return google_id_token.verify_oauth2_token(token, google_requests.Request(), client_id)


def identity_from_claims(claims: dict[str, Any]) -> GoogleIdentity:
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleAuthError("token issuer is not Google")
    subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(subject, str) or not subject:
        raise GoogleAuthError("token has no subject")
    if not isinstance(email, str) or not email.strip():
        raise GoogleAuthError("token has no email")
    if claims.get("email_verified") is not True:
        raise GoogleAuthError("Google email is not verified")
    name = claims.get("name")
    return GoogleIdentity(
        subject=subject,
        email=email.strip().lower(),
        full_name=name.strip() if isinstance(name, str) and name.strip() else None,
    )


def verify_google_id_token(token: str, client_id: str, *, verifier: Verifier | None = None) -> GoogleIdentity:
    if not token or not client_id:
        raise GoogleAuthError("missing token or client ID")
    try:
        claims = (verifier or _default_verifier)(token, client_id)
    except GoogleAuthError:
        raise
    except Exception as exc:
        # Bad signature, wrong audience, expired, or a network problem. Don't leak which.
        raise GoogleAuthError("invalid Google token") from exc
    return identity_from_claims(claims)
