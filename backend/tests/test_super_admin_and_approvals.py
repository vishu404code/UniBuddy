from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.services.providers import get_auth_admin_client, get_supabase_client
from app.services.provisioning import ProvisioningError, provision_by_super_admin
from app.services.registration_review import approve_registration, reject_registration
from app.services.documents import DocumentConflict, DocumentNotFound
from tests.conftest import FakeProfileRepository, make_profile
from tests.fakes import FakeAuthAdmin, FakeSupabase

API = settings.api_v1_prefix
CAMPUS_A = str(uuid4())
CAMPUS_B = str(uuid4())
DEPT_A = str(uuid4())
SUPER = str(uuid4())
AUTH_A = str(uuid4())
STUDENT = str(uuid4())
MANAGER = str(uuid4())


def _world():
    sb = FakeSupabase()
    sb.tables["campuses"] += [{"id": CAMPUS_A, "name": "Campus A", "code": "a"},
                              {"id": CAMPUS_B, "name": "Campus B", "code": "b"}]
    sb.tables["departments"] += [{"id": DEPT_A, "campus_id": CAMPUS_A, "name": "CS"}]
    for user_id, role, campus in [(SUPER, "super_admin", None), (AUTH_A, "authority", CAMPUS_A),
                                  (MANAGER, "management", None)]:
        sb.tables["profiles"].append({"id": user_id, "email": f"{role}@nst.rishihood.edu.in", "role": role,
                                      "campus_id": campus, "department_id": None,
                                      "cross_campus_record_access": False, "full_name": role})
    return sb


def _actor(user_id, role, campus=None):
    return make_profile(user_id, role=role, campus_id=campus)


@pytest.mark.asyncio
async def test_super_admin_invites_an_authority_to_the_campus_it_chooses():
    sb, auth = _world(), FakeAuthAdmin()

    created = await provision_by_super_admin(sb=sb, auth_admin=auth, actor=_actor(SUPER, "super_admin"),
                                             email="new.auth@nst.rishihood.edu.in", full_name="New Authority",
                                             role="authority", campus_id=CAMPUS_B)

    assert created["role"] == "authority"
    assert created["campus_id"] == CAMPUS_B
    assert len(auth.invites) == 1


@pytest.mark.asyncio
async def test_authority_account_without_a_campus_is_refused_before_any_invitation():
    sb, auth = _world(), FakeAuthAdmin()

    with pytest.raises(ProvisioningError) as info:
        await provision_by_super_admin(sb=sb, auth_admin=auth, actor=_actor(SUPER, "super_admin"),
                                       email="x@nst.rishihood.edu.in", full_name="X Y", role="authority",
                                       campus_id=None)
    assert info.value.status_code == 422
    assert auth.invites == []


@pytest.mark.asyncio
async def test_management_may_be_invited_without_a_campus():
    sb, auth = _world(), FakeAuthAdmin()

    created = await provision_by_super_admin(sb=sb, auth_admin=auth, actor=_actor(SUPER, "super_admin"),
                                             email="mgr@nst.rishihood.edu.in", full_name="Manager",
                                             role="management", campus_id=None)

    assert created["campus_id"] is None
    assert created["role"] == "management"


@pytest.mark.asyncio
async def test_unknown_campus_is_refused_by_the_database_rules():
    sb, auth = _world(), FakeAuthAdmin()

    with pytest.raises(ProvisioningError) as info:
        await provision_by_super_admin(sb=sb, auth_admin=auth, actor=_actor(SUPER, "super_admin"),
                                       email="x@nst.rishihood.edu.in", full_name="X Y", role="authority",
                                       campus_id=str(uuid4()))
    assert info.value.status_code == 422
    assert auth.invites == []


@pytest.mark.asyncio
async def test_registration_approval_joins_the_approvers_campus_and_marks_the_request():
    sb, auth = _world(), FakeAuthAdmin()
    request_id = str(uuid4())
    sb.tables["registration_requests"].append({"id": request_id, "email": "new.student@nst.rishihood.edu.in",
                                               "full_name": "New Student", "status": "pending",
                                               "requested_at": "2026-11-01T10:00:00+00:00"})

    created = await approve_registration(sb=sb, auth_admin=auth, actor=_actor(AUTH_A, "authority", CAMPUS_A),
                                         request_id=request_id)

    assert created["role"] == "student"
    assert created["campus_id"] == CAMPUS_A
    row = sb.tables["registration_requests"][0]
    assert row["status"] == "approved"
    assert row["decided_by"] == AUTH_A


@pytest.mark.asyncio
async def test_a_request_can_only_be_decided_once():
    sb, auth = _world(), FakeAuthAdmin()
    request_id = str(uuid4())
    sb.tables["registration_requests"].append({"id": request_id, "email": "once@nst.rishihood.edu.in",
                                               "full_name": "Once", "status": "pending",
                                               "requested_at": "2026-11-01T10:00:00+00:00"})
    actor = _actor(AUTH_A, "authority", CAMPUS_A)
    await approve_registration(sb=sb, auth_admin=auth, actor=actor, request_id=request_id)

    with pytest.raises(DocumentConflict):
        await approve_registration(sb=sb, auth_admin=auth, actor=actor, request_id=request_id)
    assert len(auth.invites) == 1


@pytest.mark.asyncio
async def test_approval_for_an_email_that_already_has_a_profile_leaves_the_request_pending():
    sb, auth = _world(), FakeAuthAdmin()
    request_id = str(uuid4())
    sb.tables["profiles"].append({"id": str(uuid4()), "email": "taken@nst.rishihood.edu.in", "role": "student",
                                  "campus_id": CAMPUS_B, "department_id": None,
                                  "cross_campus_record_access": False})
    sb.tables["registration_requests"].append({"id": request_id, "email": "taken@nst.rishihood.edu.in",
                                               "full_name": "Taken", "status": "pending",
                                               "requested_at": "2026-11-01T10:00:00+00:00"})

    with pytest.raises(ProvisioningError) as info:
        await approve_registration(sb=sb, auth_admin=auth, actor=_actor(AUTH_A, "authority", CAMPUS_A),
                                   request_id=request_id)
    assert info.value.status_code == 409
    assert sb.tables["registration_requests"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_rejection_is_recorded_once_with_the_decider():
    sb = _world()
    request_id = str(uuid4())
    sb.tables["registration_requests"].append({"id": request_id, "email": "no@nst.rishihood.edu.in",
                                               "full_name": "No", "status": "pending",
                                               "requested_at": "2026-11-01T10:00:00+00:00"})

    row = await reject_registration(sb=sb, actor=_actor(AUTH_A, "authority", CAMPUS_A),
                                    request_id=request_id, reason="Not eligible")

    assert row["status"] == "rejected"
    assert row["decision_reason"] == "Not eligible"
    with pytest.raises(DocumentConflict):
        await reject_registration(sb=sb, actor=_actor(AUTH_A, "authority", CAMPUS_A),
                                  request_id=request_id, reason=None)


@pytest.mark.asyncio
async def test_unknown_request_is_not_found():
    with pytest.raises(DocumentNotFound):
        await reject_registration(sb=_world(), actor=_actor(AUTH_A, "authority", CAMPUS_A),
                                  request_id=str(uuid4()), reason=None)


# --- Routes: role boundaries ---

class _Verifier:
    def verify(self, token):
        import uuid
        return uuid.UUID(token)


def _client(sb, auth):
    profiles = {}
    for row in sb.tables["profiles"]:
        profiles[row["id"]] = make_profile(row["id"], role=row["role"], campus_id=row["campus_id"])
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    app.dependency_overrides[get_supabase_client] = lambda: sb
    app.dependency_overrides[get_auth_admin_client] = lambda: auth
    return TestClient(app)


@pytest.fixture(autouse=True)
def _overrides(monkeypatch):
    yield
    app.dependency_overrides.clear()


def _h(user_id):
    return {"Authorization": f"Bearer {user_id}"}


def test_authority_cannot_invite_authority_or_management_accounts():
    sb, auth = _world(), FakeAuthAdmin()
    client = _client(sb, auth)
    for path in ("authority", "management"):
        response = client.post(f"{API}/provisioning/{path}", headers=_h(AUTH_A),
                               json={"email": "x@nst.rishihood.edu.in", "full_name": "X Y", "campus_id": CAMPUS_A})
        assert response.status_code == 403
    assert auth.invites == []


def test_super_admin_cannot_invite_students_or_faculty_here():
    sb, auth = _world(), FakeAuthAdmin()
    client = _client(sb, auth)
    response = client.post(f"{API}/provisioning/students", headers=_h(SUPER),
                           json={"email": "s@nst.rishihood.edu.in", "full_name": "S T"})
    assert response.status_code == 403
    assert auth.invites == []


def test_super_admin_invite_route_refuses_a_campus_field_on_students_and_role_fields_everywhere():
    sb, auth = _world(), FakeAuthAdmin()
    client = _client(sb, auth)
    response = client.post(f"{API}/provisioning/authority", headers=_h(SUPER),
                           json={"email": "a@nst.rishihood.edu.in", "full_name": "A B", "campus_id": CAMPUS_B,
                                 "role": "super_admin"})
    assert response.status_code == 422
    assert auth.invites == []


def test_campus_authority_sees_pending_requests_and_its_own_departments_only():
    sb, auth = _world(), FakeAuthAdmin()
    sb.tables["registration_requests"].append({"id": str(uuid4()), "email": "p@nst.rishihood.edu.in",
                                               "full_name": "P Q", "status": "pending",
                                               "requested_at": "2026-11-01T10:00:00+00:00"})
    sb.tables["departments"].append({"id": str(uuid4()), "campus_id": CAMPUS_B, "name": "Other"})
    client = _client(sb, auth)

    pending = client.get(f"{API}/provisioning/registrations", headers=_h(AUTH_A))
    departments = client.get(f"{API}/provisioning/departments", headers=_h(AUTH_A))

    assert pending.status_code == 200 and len(pending.json()) == 1
    assert [d["name"] for d in departments.json()] == ["CS"]


def test_students_cannot_read_pending_registrations_or_the_account_list():
    sb, auth = _world(), FakeAuthAdmin()
    client = _client(sb, auth)
    student = str(uuid4())
    sb.tables["profiles"].append({"id": student, "email": "st@nst.rishihood.edu.in", "role": "student",
                                  "campus_id": CAMPUS_A, "department_id": None,
                                  "cross_campus_record_access": False, "full_name": "St"})
    assert client.get(f"{API}/provisioning/registrations", headers=_h(student)).status_code == 403
    assert client.get(f"{API}/admin/accounts", headers=_h(student)).status_code == 403


def test_management_cannot_read_the_account_list_or_review_registrations():
    sb, auth = _world(), FakeAuthAdmin()
    client = _client(sb, auth)
    assert client.get(f"{API}/admin/accounts", headers=_h(MANAGER)).status_code == 403
    assert client.get(f"{API}/provisioning/registrations", headers=_h(MANAGER)).status_code == 403


def test_super_admin_account_list_comes_from_the_database_function():
    sb, auth = _world(), FakeAuthAdmin()
    sb.rpc_responses["super_admin_list_accounts"] = [{"id": AUTH_A, "email": "a@nst.rishihood.edu.in",
                                                     "full_name": "A", "role": "authority", "campus_id": CAMPUS_A,
                                                     "campus_name": "Campus A", "created_at": "2026-11-01T10:00:00+00:00"}]
    client = _client(sb, auth)
    response = client.get(f"{API}/admin/accounts", headers=_h(SUPER))
    assert response.status_code == 200
    assert response.json()[0]["role"] == "authority"
    assert sb.rpc_calls[-1][1] == "super_admin_list_accounts"
    assert "question" not in response.text


def test_super_admin_lists_campuses_for_the_invitation_form():
    sb, auth = _world(), FakeAuthAdmin()
    client = _client(sb, auth)
    response = client.get(f"{API}/provisioning/campuses", headers=_h(SUPER))
    assert response.status_code == 200
    assert {c["name"] for c in response.json()} == {"Campus A", "Campus B"}
    assert client.get(f"{API}/provisioning/campuses", headers=_h(AUTH_A)).status_code == 403
