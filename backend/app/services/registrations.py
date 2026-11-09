from app.schemas.registration import RegistrationRequestIn
from app.services.supabase_client import SupabaseClient, SupabaseError

RECEIPT_MESSAGE = (
    "Thanks. If this address is eligible, you will receive an invitation to set your password "
    "after review."
)


async def submit_registration(
    *, sb: SupabaseClient, body: RegistrationRequestIn
) -> dict:
    """Stores a pending request. It grants no role and creates no account.

    The response is the same whether or not the address already has a request or an account,
    so the endpoint does not reveal who has registered.
    """

    try:
        await sb.insert_service(
            "registration_requests",
            [{"email": body.email, "full_name": body.full_name}],
        )
    except SupabaseError as exc:
        if exc.status_code != 409:
            raise
    return {"status": "received", "message": RECEIPT_MESSAGE}
