from typing import Annotated

from fastapi import APIRouter, Depends

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.provisioning import AccountOut
from app.services.providers import get_supabase_client
from app.services.supabase_client import SupabaseClient

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    session: Annotated[CurrentSession, Depends(session_with_roles("super_admin"))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    """Super Admin only. The database checks the caller's role again and returns account fields only."""
    return await sb.rpc_as_user(session.access_token, "super_admin_list_accounts", {})
