"""Creates the account row for an invitation, replacing Supabase Auth's invite call.

The row has no Google subject yet. The person links it by signing in with Google using the
same verified email. Until then the row grants no access, because roles live only on profiles.
"""

from uuid import UUID, uuid4


class PostgresAccountDirectory:
    def __init__(self, sb):
        self._sb = sb

    async def invite_user(self, email: str, full_name: str) -> UUID:
        email = email.strip().lower()
        # Reuse an account row left by an earlier attempt that never got a profile.
        for row in await self._sb.select_service("account_identities", {"select": "id", "email": f"eq.{email}"}):
            with_profile = await self._sb.select_service("profiles", {"select": "id", "id": f"eq.{row['id']}"})
            if not with_profile:
                return UUID(str(row["id"]))
        new_id = uuid4()
        await self._sb.insert_service("account_identities", [{"id": str(new_id), "email": email}])
        return new_id

    async def delete_user(self, user_id: UUID) -> None:
        # Deliberately a no-op: the database grants no delete on account_identities. A row
        # without a profile grants no access, and a retry reuses it.
        return None
