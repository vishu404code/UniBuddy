"""Verifies UniBuddy's own session tokens (see app/auth/session.py)."""

from uuid import UUID


class InvalidAccessToken(Exception):
    """The token is missing, forged, expired, or for another service."""


class SessionTokenVerifier:
    """verify(token) returns the user ID or raises InvalidAccessToken. Roles are never read here."""

    def __init__(self, secret: str):
        self._secret = secret

    def verify(self, token: str) -> UUID:
        from app.auth.session import SessionError, read_session_token

        try:
            return read_session_token(token, self._secret)
        except SessionError as exc:
            raise InvalidAccessToken("invalid session") from exc
