from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.services.token_verifier import InvalidAccessToken

USER_ID = "11111111-1111-1111-1111-111111111111"


def test_valid_token_returns_user_id(verifier, make_token):
    token = make_token(USER_ID)

    assert verifier.verify(token) == UUID(USER_ID)


def test_expired_token_is_rejected(verifier, make_token):
    token = make_token(USER_ID, expires_in=-60)

    with pytest.raises(InvalidAccessToken):
        verifier.verify(token)


def test_wrong_audience_is_rejected(verifier, make_token):
    token = make_token(USER_ID, aud="anon")

    with pytest.raises(InvalidAccessToken):
        verifier.verify(token)


def test_wrong_issuer_is_rejected(verifier, make_token):
    token = make_token(USER_ID, iss="https://evil.example.com/auth/v1")

    with pytest.raises(InvalidAccessToken):
        verifier.verify(token)


def test_token_signed_with_other_key_is_rejected(verifier, make_token):
    other_key = ec.generate_private_key(ec.SECP256R1())
    token = make_token(USER_ID, key=other_key)

    with pytest.raises(InvalidAccessToken):
        verifier.verify(token)


def test_hs256_token_is_rejected(verifier):
    token = jwt.encode(
        {"sub": USER_ID, "aud": "authenticated", "iss": "https://test-project.supabase.co/auth/v1",
         "iat": 0, "exp": 9999999999},
        "test-only-shared-secret-that-is-long-enough-for-hs256",
        algorithm="HS256",
    )

    with pytest.raises(InvalidAccessToken):
        verifier.verify(token)


def test_unsigned_token_is_rejected(verifier):
    token = jwt.encode(
        {"sub": USER_ID, "aud": "authenticated", "iss": "https://test-project.supabase.co/auth/v1",
         "iat": 0, "exp": 9999999999},
        key="",
        algorithm="none",
    )

    with pytest.raises(InvalidAccessToken):
        verifier.verify(token)


def test_token_without_subject_is_rejected(verifier, signing_key):
    payload = {"aud": "authenticated", "iss": "https://test-project.supabase.co/auth/v1",
               "iat": 0, "exp": 9999999999}
    token = jwt.encode(payload, signing_key, algorithm="ES256")

    with pytest.raises(InvalidAccessToken):
        verifier.verify(token)


def test_non_uuid_subject_is_rejected(verifier, make_token):
    token = make_token("not-a-uuid")

    with pytest.raises(InvalidAccessToken):
        verifier.verify(token)


def test_garbage_token_is_rejected(verifier):
    with pytest.raises(InvalidAccessToken):
        verifier.verify("this-is-not-a-jwt")
