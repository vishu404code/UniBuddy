from typing import Any

import httpx


class SupabaseError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Supabase request failed with HTTP {status_code}")
        self.status_code = status_code
        self.detail = detail


class SupabaseClient:
    """Thin client for Supabase PostgREST, RPC and Storage.

    Two kinds of call:
    - service calls use the secret key. They bypass RLS, so callers must do their
      own authorization before calling them.
    - user calls use the caller's access token with the publishable key, so RLS
      applies to the result.
    """

    def __init__(
        self,
        supabase_url: str,
        secret_key: str,
        publishable_key: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        base = supabase_url.rstrip("/")
        self._rest = f"{base}/rest/v1"
        self._rpc = f"{base}/rest/v1/rpc"
        self._storage = f"{base}/storage/v1"
        self._secret_key = secret_key
        self._publishable_key = publishable_key
        self._transport = transport

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=60.0)

    def _service_headers(self) -> dict[str, str]:
        return {"apikey": self._secret_key}

    def _user_headers(self, access_token: str) -> dict[str, str]:
        if not self._publishable_key:
            raise SupabaseError(503, "Publishable key is not configured")
        return {"apikey": self._publishable_key, "Authorization": f"Bearer {access_token}"}

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise SupabaseError(response.status_code, response.text[:500])

    # --- service calls (secret key, bypass RLS) ---

    async def select_service(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        async with self._http() as client:
            response = await client.get(f"{self._rest}/{table}", params=params, headers=self._service_headers())
        self._raise_for_status(response)
        return response.json()

    async def select_all_service(self, table: str, params: dict[str, str], page_size: int = 1000) -> list[dict[str, Any]]:
        """Read every matching row. PostgREST caps single responses, so this pages through them."""
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.select_service(table, {**params, "limit": str(page_size), "offset": str(offset)})
            rows.extend(page)
            if len(page) < page_size:
                return rows
            offset += page_size

    async def insert_service(self, table: str, rows: list[dict[str, Any]]) -> None:
        headers = {**self._service_headers(), "Prefer": "return=minimal", "Content-Type": "application/json"}
        async with self._http() as client:
            response = await client.post(f"{self._rest}/{table}", json=rows, headers=headers)
        self._raise_for_status(response)

    async def update_service(
        self, table: str, filters: dict[str, str], values: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Update matching rows and return them. An empty list means nothing matched, e.g. a concurrent change."""
        headers = {**self._service_headers(), "Prefer": "return=representation", "Content-Type": "application/json"}
        async with self._http() as client:
            response = await client.patch(f"{self._rest}/{table}", params=filters, json=values, headers=headers)
        self._raise_for_status(response)
        return response.json()

    async def upload_object(self, bucket: str, path: str, content: bytes, content_type: str) -> None:
        headers = {
            **self._service_headers(),
            "Content-Type": content_type,
            "x-upsert": "false",
        }
        async with self._http() as client:
            response = await client.post(f"{self._storage}/object/{bucket}/{path}", content=content, headers=headers)
        self._raise_for_status(response)

    # --- user calls (publishable key + user access token, RLS applies) ---

    async def select_as_user(self, access_token: str, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        async with self._http() as client:
            response = await client.get(
                f"{self._rest}/{table}", params=params, headers=self._user_headers(access_token)
            )
        self._raise_for_status(response)
        return response.json()

    async def rpc_as_user(self, access_token: str, function: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        headers = {**self._user_headers(access_token), "Content-Type": "application/json"}
        async with self._http() as client:
            response = await client.post(f"{self._rpc}/{function}", json=payload, headers=headers)
        self._raise_for_status(response)
        return response.json()
