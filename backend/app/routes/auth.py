from fastapi import APIRouter, Depends

from app.config import settings
from app.middleware.auth import get_current_user
from app.schemas.auth import CurrentUser
from app.schemas.registration import RegistrationReceiptOut, RegistrationRequestIn
from app.schemas.auth import GoogleTokenIn, SessionOut
from app.services.google_sign_in import GoogleSignInError, request_student_access, sign_in
from app.services.providers import get_google_verifier, get_data_client
from app.services.registrations import submit_registration
from app.services.postgres_client import PostgresClient
from fastapi import HTTPException

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=CurrentUser)
async def read_current_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user


@router.post("/registrations", response_model=RegistrationReceiptOut, status_code=202)
async def register_student(
    body: RegistrationRequestIn,
    sb: PostgresClient = Depends(get_data_client),
):
    """Public. Queues a student registration for review. Grants nothing."""
    receipt = await submit_registration(
        sb=sb, body=body
    )
    return RegistrationReceiptOut(**receipt)


@router.post("/google", response_model=SessionOut)
async def google_sign_in(
    body: GoogleTokenIn,
    sb: PostgresClient = Depends(get_data_client),
    verifier=Depends(get_google_verifier),
):
    """Signs in a person whose Google identity matches an existing UniBuddy account."""
    try:
        session = await sign_in(
            sb=sb, id_token=body.id_token, client_id=settings.google_client_id,
            session_secret=settings.session_secret, verifier=verifier,
        )
    except GoogleSignInError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
    return SessionOut(**session)


@router.post("/google/access-request", status_code=202)
async def google_access_request(
    body: GoogleTokenIn,
    sb: PostgresClient = Depends(get_data_client),
    verifier=Depends(get_google_verifier),
):
    """Files a pending Student request for a Google-verified person. Grants nothing."""
    try:
        return await request_student_access(
            sb=sb, id_token=body.id_token, client_id=settings.google_client_id, verifier=verifier,
        )
    except GoogleSignInError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc

