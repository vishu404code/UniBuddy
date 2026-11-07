from fastapi import APIRouter, Depends

from app.middleware.auth import get_current_user
from app.schemas.auth import CurrentUser

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=CurrentUser)
async def read_current_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user
