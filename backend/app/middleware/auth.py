from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.repositories.profiles import ProfileLookupError, ProfileRepository
from app.schemas.auth import CurrentUser, Role
from app.services.providers import get_data_client
from app.services.token_verifier import InvalidAccessToken, SessionTokenVerifier

bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class CurrentSession:
    user: CurrentUser
    access_token: str


def get_token_verifier() -> SessionTokenVerifier:
    if not settings.session_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is not configured")
    return SessionTokenVerifier(settings.session_secret)


def get_profile_repository() -> ProfileRepository:
    return ProfileRepository(get_data_client())


async def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    verifier: SessionTokenVerifier = Depends(get_token_verifier),
    profiles: ProfileRepository = Depends(get_profile_repository),
) -> CurrentSession:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", _UNAUTHORIZED_HEADERS)

    try:
        user_id: UUID = verifier.verify(credentials.credentials)
    except InvalidAccessToken as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", _UNAUTHORIZED_HEADERS) from exc

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
