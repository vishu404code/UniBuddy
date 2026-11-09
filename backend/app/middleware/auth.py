from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.repositories.profiles import ProfileLookupError, ProfileRepository
from app.schemas.auth import CurrentUser, Role
from app.services.token_verifier import (
    AuthServiceUnavailable,
    InvalidAccessToken,
    SupabaseTokenVerifier,
)

bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class CurrentSession:
    user: CurrentUser
    access_token: str


@lru_cache
def _build_token_verifier() -> SupabaseTokenVerifier:
    if not settings.supabase_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is not configured")
    return SupabaseTokenVerifier.for_project(settings.supabase_url)


def get_token_verifier():
    if settings.auth_backend == "google":
        from app.services.token_verifier import SessionTokenVerifier

        if not settings.session_secret:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is not configured")
        return SessionTokenVerifier(settings.session_secret)
    return _build_token_verifier()


def get_profile_repository():
    if settings.auth_backend == "google":
        from app.repositories.profiles import ClientProfileRepository
        from app.services.providers import get_supabase_client

        return ClientProfileRepository(get_supabase_client())
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is not configured")
    return ProfileRepository(settings.supabase_url, settings.supabase_secret_key)


async def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    verifier: SupabaseTokenVerifier = Depends(get_token_verifier),
    profiles: ProfileRepository = Depends(get_profile_repository),
) -> CurrentSession:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", _UNAUTHORIZED_HEADERS)

    try:
        user_id: UUID = verifier.verify(credentials.credentials)
    except InvalidAccessToken as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", _UNAUTHORIZED_HEADERS) from exc
    except AuthServiceUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication service unavailable") from exc

    try:
        profile = await profiles.get_by_id(user_id)
    except ProfileLookupError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not load user profile") from exc

    if profile is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No UniBuddy profile exists for this account")
    return CurrentSession(user=profile, access_token=credentials.credentials)


async def get_current_user(session: CurrentSession = Depends(get_current_session)) -> CurrentUser:
    return session.user


def session_with_roles(*allowed_roles: Role):
    async def checker(session: CurrentSession = Depends(get_current_session)) -> CurrentSession:
        if session.user.role not in allowed_roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role cannot perform this action")
        return session

    return checker


def require_roles(*allowed_roles: Role):
    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role cannot perform this action")
        return user

    return checker
