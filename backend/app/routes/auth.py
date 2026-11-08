from fastapi import APIRouter, Depends

from app.config import settings
from app.middleware.auth import get_current_user
from app.schemas.auth import CurrentUser
from app.schemas.registration import RegistrationReceiptOut, RegistrationRequestIn
from app.services.providers import get_supabase_client
from app.services.registrations import submit_registration
from app.services.supabase_client import SupabaseClient

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=CurrentUser)
async def read_current_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user


@router.post("/registrations", response_model=RegistrationReceiptOut, status_code=202)
async def register_student(
    body: RegistrationRequestIn,
    sb: SupabaseClient = Depends(get_supabase_client),
):
    """Public. Queues a student registration for review. Grants nothing."""
    receipt = await submit_registration(
        sb=sb, body=body, allowed_domains=settings.provisioning_allowed_domains_set
    )
    return RegistrationReceiptOut(**receipt)
