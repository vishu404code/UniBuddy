from uuid import UUID

from app.schemas.auth import CurrentUser

PROFILE_COLUMNS = "id,email,full_name,role,campus_id,department_id,cross_campus_record_access"


class ProfileLookupError(Exception):
    """The profiles table could not be read."""


class ProfileRepository:
    """Profile lookup through the data client. Server-side only: pass only a user ID that came
    from a verified session token. The role and campus come from this row, never from a token."""

    def __init__(self, client):
        self._client = client

    async def get_by_id(self, user_id: UUID) -> CurrentUser | None:
        try:
            rows = await self._client.select_service("profiles", {"select": PROFILE_COLUMNS, "id": f"eq.{user_id}"})
        except Exception as exc:
            raise ProfileLookupError("Profile lookup request failed") from exc
        if not rows:
            return None
        return CurrentUser(**rows[0])
