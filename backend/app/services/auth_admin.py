from uuid import UUID

import httpx


class AuthAdminError(Exception):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class AuthAdminClient:
    """Supabase Auth Admin API, called with the secret key (server-side only).

    `invite_user` sends a real invitation email. Tests must use a fake client.
    """

    def __init__(self, supabase_url: str, secret_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self._base = f"{supabase_url.rstrip('/')}/auth/v1"
        self._headers = {"apikey": secret_key, "Content-Type": "application/json"}
        self._transport = transport

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=30.0)

    async def invite_user(self, email: str, full_name: str) -> UUID:
        try:
            async with self._http() as client:
                response = await client.post(
                    f"{self._base}/invite",
                    headers=self._headers,
                    json={"email": email, "data": {"full_name": full_name}},
                )
        except httpx.HTTPError as exc:
            raise AuthAdminError("invite_unreachable", 502) from exc

        if response.status_code in (200, 201):
            return UUID(response.json()["id"])
        body = response.text.lower()
        if response.status_code in (409, 422) and ("email_exists" in body or "already" in body or "registered" in body):
            raise AuthAdminError("account_exists", 409)
        raise AuthAdminError("invite_failed", 502)

    async def delete_user(self, user_id: UUID) -> None:
        try:
            async with self._http() as client:
                response = await client.delete(f"{self._base}/admin/users/{user_id}", headers=self._headers)
        except httpx.HTTPError as exc:
            raise AuthAdminError("delete_unreachable", 502) from exc
        if response.status_code not in (200, 204):
            raise AuthAdminError("delete_failed", 502)
