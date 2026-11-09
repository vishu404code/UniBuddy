from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.schemas.registration import RegistrationRequestIn
from app.services.provisioning import ProvisioningError
from app.services.registrations import RECEIPT_MESSAGE, submit_registration
from app.services.providers import get_data_client
from tests.fakes import FakeDataClient

API = settings.api_v1_prefix


def _body(email="Student.One@NST.rishihood.edu.in", name="  Student   One "):
    return RegistrationRequestIn(email=email, full_name=name)


@pytest.mark.asyncio
async def test_registration_stores_a_pending_request_and_grants_nothing():
    sb = FakeDataClient()
    sb.tables["profiles"] = []

    receipt = await submit_registration(sb=sb, body=_body())

    assert receipt == {"status": "received", "message": RECEIPT_MESSAGE}
    row = sb.tables["registration_requests"][0]
    assert row["email"] == "student.one@nst.rishihood.edu.in"
    assert row["full_name"] == "Student One"
    assert sb.tables["profiles"] == []


@pytest.mark.asyncio
async def test_repeat_submission_gets_the_same_receipt_without_a_second_row():
    sb = FakeDataClient()
    first = await submit_registration(sb=sb, body=_body())
    second = await submit_registration(sb=sb, body=_body())

    assert first == second
    assert len(sb.tables["registration_requests"]) == 1


def test_public_route_accepts_only_email_and_name(monkeypatch):
    sb = FakeDataClient()
    app.dependency_overrides[get_data_client] = lambda: sb
    try:
        client = TestClient(app)
        ok = client.post(f"{API}/auth/registrations",
                         json={"email": "new.student@nst.rishihood.edu.in", "full_name": "New Student"})
        assert ok.status_code == 202
        assert ok.json()["status"] == "received"

        smuggled = client.post(f"{API}/auth/registrations",
                               json={"email": "x@nst.rishihood.edu.in", "full_name": "X Y", "role": "authority"})
        assert smuggled.status_code == 422

        other_domain = client.post(f"{API}/auth/registrations",
                                   json={"email": "x@gmail.com", "full_name": "X Y"})
        assert other_domain.status_code == 202
    finally:
        app.dependency_overrides.clear()
    assert len(sb.tables["registration_requests"]) == 2
