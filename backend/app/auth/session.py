"""UniBuddy's own session token, issued after Google verifies the person.

The token carries only the internal user ID and timing claims. It never carries a
role, campus or department. Every request loads those from the database.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

SESSION_ISSUER = "unibuddy-api"
SESSION_AUDIENCE = "unibuddy-web"
ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32
DEFAULT_LIFETIME = timedelta(hours=8)


class SessionError(Exception):
    """The session token is missing, forged, expired, or for another service."""


def _require_secret(secret: str) -> None:
    if not secret or len(secret) < MIN_SECRET_LENGTH:
        raise SessionError("session secret is missing or too short")


def issue_session_token(
    user_id: UUID,
    secret: str,
    *,
    lifetime: timedelta = DEFAULT_LIFETIME,
    now: datetime | None = None,
) -> str:
    _require_secret(secret)
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iss": SESSION_ISSUER,
        "aud": SESSION_AUDIENCE,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + lifetime).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def read_session_token(token: str, secret: str) -> UUID:
    _require_secret(secret)
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            audience=SESSION_AUDIENCE,
            issuer=SESSION_ISSUER,
            options={"require": ["sub", "iss", "aud", "iat", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise SessionError("invalid or expired session") from exc
    try:
        return UUID(claims["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise SessionError("session has no valid user") from exc
