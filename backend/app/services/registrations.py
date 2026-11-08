from app.schemas.registration import RegistrationRequestIn
from app.services.provisioning import ProvisioningError, email_domain
from app.services.supabase_client import SupabaseClient, SupabaseError

RECEIPT_MESSAGE = (
    "Thanks. If this address is eligible, you will receive an invitation to set your password "
    "after review."
)


async def submit_registration(
    *, sb: SupabaseClient, body: RegistrationRequestIn, allowed_domains: frozenset[str]
) -> dict:
    """Stores a pending request. It grants no role and creates no account.

    The response is the same whether or not the address already has a request or an account,
    so the endpoint does not reveal who has registered.
    """
    if not allowed_domains:
        raise ProvisioningError(503, "Registration is not available right now")
    if email_domain(body.email) not in allowed_domains:
        raise ProvisioningError(422, "Registration is limited to approved university email domains")

    try:
        await sb.insert_service(
            "registration_requests",
            [{"email": body.email, "full_name": body.full_name}],
        )
    except SupabaseError as exc:
        if exc.status_code != 409:
            raise
    return {"status": "received", "message": RECEIPT_MESSAGE}
