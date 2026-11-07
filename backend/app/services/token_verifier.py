from uuid import UUID

import jwt
from jwt import PyJWKClient

# Asymmetric algorithms only. Accepting HS256 here would let a token signed
# with a shared secret pass, and "none" must never be accepted.
ALLOWED_ALGORITHMS = ["ES256", "RS256"]
REQUIRED_CLAIMS = ["exp", "iat", "sub", "aud", "iss"]
EXPECTED_AUDIENCE = "authenticated"


class InvalidAccessToken(Exception):
    """The bearer token is missing, malformed, expired or not trusted."""


class AuthServiceUnavailable(Exception):
    """Signing keys could not be fetched, so tokens cannot be checked."""


class SupabaseTokenVerifier:
    def __init__(self, issuer: str, jwks_client: PyJWKClient):
        self._issuer = issuer
        self._jwks_client = jwks_client

    @classmethod
    def for_project(cls, supabase_url: str) -> "SupabaseTokenVerifier":
        issuer = f"{supabase_url.rstrip('/')}/auth/v1"
        jwks_client = PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True)
        return cls(issuer=issuer, jwks_client=jwks_client)

    def verify(self, token: str) -> UUID:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthServiceUnavailable("Could not fetch Supabase signing keys") from exc
        except jwt.PyJWTError as exc:
            raise InvalidAccessToken("Token has no usable signing key") from exc

        try:
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=EXPECTED_AUDIENCE,
                issuer=self._issuer,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as exc:
            raise InvalidAccessToken("Token failed verification") from exc

        try:
            return UUID(claims["sub"])
        except (TypeError, ValueError) as exc:
            raise InvalidAccessToken("Token subject is not a valid user id") from exc
