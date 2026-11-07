from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.schemas.auth import CurrentUser

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"


@pytest.fixture
def signing_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def make_token(signing_key):
    def _make(
        sub: str,
        *,
        key=None,
        aud: str = "authenticated",
        iss: str = TEST_ISSUER,
        expires_in: int = 3600,
        algorithm: str = "ES256",
        extra_claims: dict | None = None,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": sub,
            "aud": aud,
            "iss": iss,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
            **(extra_claims or {}),
        }
        return jwt.encode(payload, key or signing_key, algorithm=algorithm)

    return _make


class FakeJWKSClient:
    """Stands in for PyJWKClient so tests never fetch Supabase's real keys."""

    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token: str):
        return SimpleNamespace(key=self._public_key)


@pytest.fixture
def verifier(signing_key):
    from app.services.token_verifier import SupabaseTokenVerifier

    return SupabaseTokenVerifier(
        issuer=TEST_ISSUER,
        jwks_client=FakeJWKSClient(signing_key.public_key()),
    )


def make_profile(
    user_id: str,
    *,
    role: str = "student",
    campus_id: str | None = None,
    department_id: str | None = None,
    all_campuses_access: bool = False,
) -> CurrentUser:
    return CurrentUser(
        id=UUID(user_id),
        email=f"{role}@example.edu",
        full_name=f"Test {role.title()}",
        role=role,
        campus_id=UUID(campus_id) if campus_id else None,
        department_id=UUID(department_id) if department_id else None,
        all_campuses_access=all_campuses_access,
    )


class FakeProfileRepository:
    def __init__(self, profiles: dict[str, CurrentUser]):
        self._profiles = profiles

    async def get_by_id(self, user_id: UUID):
        return self._profiles.get(str(user_id))
