from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.options import FilterOptionCreate, FilterOptionOut, FilterOptionPatch
from app.services.options import create_option, list_options, remove_option, set_option_active
from app.services.postgres_client import PostgresClient
from app.services.providers import get_data_client

router = APIRouter(prefix="/filter-options", tags=["filter-options"])


@router.get("", response_model=list[FilterOptionOut])
async def options_for_my_campus(
    session: Annotated[CurrentSession, Depends(session_with_roles("faculty", "authority"))],
    include_inactive: Annotated[bool, Query()] = False,
    sb: PostgresClient = Depends(get_data_client),
):
    """Academic years, batch years and sections on the caller's campus. Faculty see active options only."""
    include = include_inactive and session.user.role == "authority"
    return await list_options(sb, session.user, include_inactive=include)


@router.post("", response_model=FilterOptionOut, status_code=201)
async def add_option(
    body: FilterOptionCreate,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await create_option(sb, session.user, body.kind, body.value)


@router.patch("/{option_id}", response_model=FilterOptionOut)
async def change_option(
    option_id: UUID,
    body: FilterOptionPatch,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await set_option_active(sb, session.user, option_id, body.active)


@router.delete("/{option_id}")
async def delete_option(
    option_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Deletes an unused option. An option in use is deactivated."""
    return await remove_option(sb, session.user, option_id)
