import json
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.schemas.auth import CurrentUser
from app.services.auth_admin import AuthAdminClient, AuthAdminError
from app.services.provisioning import ProvisioningError, provision_user
from app.services.providers import get_auth_admin_client, get_supabase_client
from app.services.supabase_client import SupabaseError
from tests.conftest import FakeProfileRepository, make_profile
from tests.fakes import FakeAuthAdmin, FakeSupabase

CAMPUS = uuid4()
OTHER_CAMPUS = uuid4()
DEPT = uuid4()
OTHER_DEPT = uuid4()


def _actor(role="authority", campus=CAMPUS):
    return CurrentUser(id=uuid4(), email=f"{role}@example.com", full_name=role.title(), role=role,
                       campus_id=campus, department_id=None)


def _world(actor):
    sb = FakeSupabase()
    sb.tables["profiles"].append({"id": str(actor.id), "email": actor.email, "role": actor.role,
                                  "campus_id": str(actor.campus_id) if actor.campus_id else None,
                                  "department_id": None, "cross_campus_record_access": False})
    sb.tables["departments"] += [
        {"id": str(DEPT), "campus_id": str(CAMPUS), "name": "CS"},
        {"id": str(OTHER_DEPT), "campus_id": str(OTHER_CAMPUS), "name": "CS"},
    ]
    return sb


async def _provision(sb, auth, actor, email="New.Student@Example.com", role="student", department_id=None):
    return await provision_user(sb=sb, auth_admin=auth, actor=actor, email=email,
                                full_name="New Student", role=role, department_id=department_id)


@pytest.mark.asyncio
async def test_authority_onboards_a_student_into_its_own_campus():
    actor = _actor()
    sb, auth = _world(actor), FakeAuthAdmin()

    created = await _provision(sb, auth, actor)

    assert created["status"] == "invited"
    assert created["campus_id"] == str(CAMPUS)
    assert created["role"] == "student"
    assert len(auth.invites) == 1
    assert auth.invites[0][0] == "new.student@example.com"
    profile = next(r for r in sb.tables["profiles"] if r["email"] == "new.student@example.com")
    assert profile["campus_id"] == str(CAMPUS)
    assert profile["cross_campus_record_access"] is False
    assert [a["outcome"] for a in sb.tables["provisioning_audit"]] == ["invited"]


@pytest.mark.asyncio
async def test_authority_onboards_faculty_with_a_department_on_its_campus():
    actor = _actor()
    sb, auth = _world(actor), FakeAuthAdmin()

    created = await _provision(sb, auth, actor, role="faculty", department_id=DEPT)

    assert created["role"] == "faculty"
    assert created["department_id"] == str(DEPT)


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name", ["student", "faculty", "management"])
async def test_only_authority_may_provision(role_name):
    actor = _actor(role=role_name)
    sb, auth = _world(actor), FakeAuthAdmin()

    with pytest.raises(ProvisioningError) as info:
        await _provision(sb, auth, actor, department_id=DEPT)

    assert info.value.status_code == 403
    assert auth.invites == []
    assert sb.tables["provisioning_audit"][-1]["reason"] == "not_authority"


@pytest.mark.asyncio
async def test_department_from_another_campus_is_refused_before_any_invitation():
    actor = _actor()
    sb, auth = _world(actor), FakeAuthAdmin()

    with pytest.raises(ProvisioningError) as info:
        await _provision(sb, auth, actor, role="faculty", department_id=OTHER_DEPT)

    assert info.value.status_code == 422
    assert auth.invites == []


@pytest.mark.asyncio
async def test_faculty_need_a_department():
    actor = _actor()
    sb, auth = _world(actor), FakeAuthAdmin()

    with pytest.raises(ProvisioningError, match="department"):
        await _provision(sb, auth, actor, role="faculty", department_id=None)
    assert auth.invites == []


@pytest.mark.asyncio
async def test_existing_profile_email_is_refused_case_insensitively():
    actor = _actor()
    sb, auth = _world(actor), FakeAuthAdmin()
    sb.tables["profiles"].append({"id": str(uuid4()), "email": "new.student@example.com", "role": "student",
                                  "campus_id": str(CAMPUS), "department_id": None,
                                  "cross_campus_record_access": False})

    with pytest.raises(ProvisioningError) as info:
        await _provision(sb, auth, actor)

    assert info.value.status_code == 409
    assert auth.invites == []


@pytest.mark.asyncio
async def test_email_that_already_has_a_login_is_refused_and_audited():
    actor = _actor()
    sb = _world(actor)
    auth = FakeAuthAdmin(invite_error=AuthAdminError("account_exists", 409))

    with pytest.raises(ProvisioningError) as info:
        await _provision(sb, auth, actor)

    assert info.value.status_code == 409
    assert sb.tables["provisioning_audit"][-1]["reason"] == "account_exists_in_auth"
    assert sb.tables["profiles"] == [sb.tables["profiles"][0]]


@pytest.mark.asyncio
async def test_failed_invitation_creates_no_profile():
    actor = _actor()
    sb = _world(actor)
    auth = FakeAuthAdmin(invite_error=AuthAdminError("invite_failed", 502))

    with pytest.raises(ProvisioningError) as info:
        await _provision(sb, auth, actor)

    assert info.value.status_code == 502
    assert len(sb.tables["profiles"]) == 1
    assert sb.tables["provisioning_audit"][-1]["outcome"] == "failed"


@pytest.mark.asyncio
async def test_profile_failure_after_invite_deletes_the_new_login():
    actor = _actor()
    sb = _world(actor)
    auth = FakeAuthAdmin()

    async def broken_complete(function, payload):
        if function == "provisioning_complete":
            raise SupabaseError(500, "database down")
        return await FakeSupabase.rpc_service(sb, function, payload)

    sb.rpc_service = broken_complete

    with pytest.raises(ProvisioningError) as info:
        await _provision(sb, auth, actor)

    assert info.value.status_code == 502
    assert auth.deleted == [auth.invites[0][2]]
    assert sb.tables["provisioning_audit"][-1]["outcome"] == "compensated"
    assert len(sb.tables["profiles"]) == 1


@pytest.mark.asyncio
async def test_failed_cleanup_is_recorded_for_manual_follow_up():
    actor = _actor()
    sb = _world(actor)
    auth = FakeAuthAdmin(delete_error=AuthAdminError("delete_failed", 502))

    async def broken_complete(function, payload):
        if function == "provisioning_complete":
            raise SupabaseError(500, "database down")
        return await FakeSupabase.rpc_service(sb, function, payload)

    sb.rpc_service = broken_complete

    with pytest.raises(ProvisioningError):
        await _provision(sb, auth, actor)

    assert sb.tables["provisioning_audit"][-1]["reason"] == "cleanup_failed"


# --- Auth Admin client: request shape only, with a mock transport (no network) ---

def _admin(handler):
    return AuthAdminClient("https://test-project.supabase.co", "sb_secret_test-only-value",
                           transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_invite_request_uses_the_secret_key_and_returns_the_new_user_id():
    seen = {}
    new_id = str(uuid4())

    def handler(request):
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers["apikey"]
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": new_id, "email": "x@example.com"})

    user_id = await _admin(handler).invite_user("x@example.com", "New Student")

    assert str(user_id) == new_id
    assert seen["url"].endswith("/auth/v1/invite")
    assert seen["apikey"] == "sb_secret_test-only-value"
    assert seen["auth"] is None
    assert seen["body"] == {"email": "x@example.com", "data": {"full_name": "New Student"}}


@pytest.mark.asyncio
async def test_invite_for_an_existing_account_maps_to_account_exists():
    def handler(request):
        return httpx.Response(422, json={"code": "email_exists", "msg": "A user with this email address has already been registered"})

    with pytest.raises(AuthAdminError) as info:
        await _admin(handler).invite_user("x@example.com", "X")
    assert info.value.code == "account_exists"


@pytest.mark.asyncio
async def test_invite_server_error_is_a_generic_failure_without_leaking_detail():
    def handler(request):
        return httpx.Response(500, text="internal stack trace with secrets")

    with pytest.raises(AuthAdminError) as info:
        await _admin(handler).invite_user("x@example.com", "X")
    assert info.value.code == "invite_failed"


@pytest.mark.asyncio
async def test_delete_user_calls_the_admin_endpoint():
    seen = {}
    user_id = uuid4()

    def handler(request):
        seen["method"], seen["url"] = request.method, str(request.url)
        return httpx.Response(200, json={})

    await _admin(handler).delete_user(user_id)

    assert seen["method"] == "DELETE"
    assert seen["url"].endswith(f"/auth/v1/admin/users/{user_id}")


# --- Routes ---

class _Verifier:
    def verify(self, token):
        import uuid
        return uuid.UUID(token)


def _route_client(actor, auth):
    sb = _world(actor)
    profiles = {str(actor.id): make_profile(str(actor.id), role=actor.role,
                                            campus_id=str(actor.campus_id) if actor.campus_id else None)}
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    app.dependency_overrides[get_supabase_client] = lambda: sb
    app.dependency_overrides[get_auth_admin_client] = lambda: auth
    return TestClient(app), sb


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_authority_route_creates_the_invited_student():
    actor = _actor()
    auth = FakeAuthAdmin()
    client, sb = _route_client(actor, auth)

    response = client.post(f"{settings.api_v1_prefix}/provisioning/students",
                           headers={"Authorization": f"Bearer {actor.id}"},
                           json={"email": "new@example.com", "full_name": "New Student"})

    assert response.status_code == 201
    assert response.json()["campus_id"] == str(CAMPUS)
    assert len(auth.invites) == 1


@pytest.mark.parametrize("role_name", ["student", "faculty", "management"])
def test_only_authority_can_call_the_provisioning_routes(role_name):
    actor = _actor(role=role_name)
    auth = FakeAuthAdmin()
    client, _ = _route_client(actor, auth)

    response = client.post(f"{settings.api_v1_prefix}/provisioning/students",
                           headers={"Authorization": f"Bearer {actor.id}"},
                           json={"email": "new@example.com", "full_name": "New Student"})

    assert response.status_code == 403
    assert auth.invites == []


@pytest.mark.parametrize("field,value", [
    ("role", "management"),
    ("campus_id", str(OTHER_CAMPUS)),
    ("all_campuses_access", True),
    ("cross_campus_record_access", True),
    ("uploaded_by", str(uuid4())),
    ("owner_id", str(uuid4())),
])
def test_client_supplied_identity_fields_are_rejected_before_any_invitation(field, value):
    actor = _actor()
    auth = FakeAuthAdmin()
    client, _ = _route_client(actor, auth)
    body = {"email": "new@example.com", "full_name": "New Student", field: value}

    response = client.post(f"{settings.api_v1_prefix}/provisioning/students",
                           headers={"Authorization": f"Bearer {actor.id}"}, json=body)

    assert response.status_code == 422
    assert auth.invites == []


def test_invalid_email_is_rejected_before_any_invitation():
    actor = _actor()
    auth = FakeAuthAdmin()
    client, _ = _route_client(actor, auth)

    response = client.post(f"{settings.api_v1_prefix}/provisioning/faculty",
                           headers={"Authorization": f"Bearer {actor.id}"},
                           json={"email": "not-an-email", "full_name": "Faculty Member", "department_id": str(DEPT)})

    assert response.status_code == 422
    assert auth.invites == []


def test_faculty_route_refuses_a_department_from_another_campus():
    actor = _actor()
    auth = FakeAuthAdmin()
    client, _ = _route_client(actor, auth)

    response = client.post(f"{settings.api_v1_prefix}/provisioning/faculty",
                           headers={"Authorization": f"Bearer {actor.id}"},
                           json={"email": "f@example.com", "full_name": "Faculty Member",
                                 "department_id": str(OTHER_DEPT)})

    assert response.status_code == 422
    assert auth.invites == []
