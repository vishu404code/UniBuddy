from types import SimpleNamespace
from uuid import UUID

import jwt
import pytest

from app.auth.session import issue_session_token
from app.schemas.auth import CurrentUser

TEST_SECRET = "test-only-session-secret-with-more-than-32-chars"


@pytest.fixture
def signing_key():
    return TEST_SECRET


@pytest.fixture
def make_token():
    """Issues a UniBuddy session token for a user ID. Extra claims are signed too, so tests can
    prove that claims are ignored: the role always comes from the profile."""

    def _make(sub: str, *, extra_claims: dict | None = None, aud: str | None = None,
              key: str | None = None, algorithm: str = "HS256") -> str:
        if not extra_claims and aud is None and key is None and algorithm == "HS256":
            return issue_session_token(UUID(sub), TEST_SECRET)
        import time

        now = int(time.time())
        payload = {
            "sub": sub,
            "iss": "unibuddy-api",
            "aud": aud or "unibuddy-web",
            "iat": now,
            "exp": now + 3600,
            **(extra_claims or {}),
        }
        return jwt.encode(payload, key or TEST_SECRET, algorithm=algorithm)

    return _make


@pytest.fixture
def verifier():
    from app.services.token_verifier import SessionTokenVerifier

    return SessionTokenVerifier(TEST_SECRET)


def make_profile(
    user_id: str,
    *,
    role: str = "student",
    campus_id: str | None = None,
    department_id: str | None = None,
    cross_campus_record_access: bool = False,
) -> CurrentUser:
    return CurrentUser(
        id=UUID(user_id),
        email=f"{role}@example.edu",
        full_name=f"Test {role.title()}",
        role=role,
        campus_id=UUID(campus_id) if campus_id else None,
        department_id=UUID(department_id) if department_id else None,
        cross_campus_record_access=cross_campus_record_access,
    )


class FakeProfileRepository:
    def __init__(self, profiles: dict[str, CurrentUser]):
        self._profiles = profiles

    async def get_by_id(self, user_id: UUID):
        return self._profiles.get(str(user_id))
