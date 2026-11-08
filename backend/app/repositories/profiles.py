from uuid import UUID

import httpx

from app.schemas.auth import CurrentUser

PROFILE_COLUMNS = "id,email,full_name,role,campus_id,department_id,cross_campus_record_access"


class ProfileLookupError(Exception):
    """The profiles table could not be read."""


class ProfileRepository:
    """Reads profile rows through Supabase's REST API with the secret API key.

    The secret key bypasses RLS, so callers must only pass a user id that came
    from a verified token. The id is typed as UUID, which keeps it out of the
    query string as raw text.
    """

    def __init__(
        self,
        supabase_url: str,
        secret_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._endpoint = f"{supabase_url.rstrip('/')}/rest/v1/profiles"
        # Secret keys are sent only in the apikey header. Authorization carries
        # user JWTs, and an sb_secret_ value there is not a JWT.
        self._headers = {"apikey": secret_key}
        self._transport = transport

    async def get_by_id(self, user_id: UUID) -> CurrentUser | None:
        params = {"select": PROFILE_COLUMNS, "id": f"eq.{user_id}"}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=10.0) as client:
                response = await client.get(self._endpoint, params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise ProfileLookupError("Profile lookup request failed") from exc

        if response.status_code != 200:
            raise ProfileLookupError(f"Profile lookup returned HTTP {response.status_code}")

        rows = response.json()
        if not rows:
            return None
        return CurrentUser(**rows[0])
