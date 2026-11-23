"""Management overview: counts come from the database rows, the route is management-only, and nothing is invented."""
import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.middleware.auth import get_profile_repository
from app.services.dashboards import management_platform_overview
from app.services.providers import get_data_client
from app.auth.session import issue_session_token
from tests.fakes import FakeDataClient

CAMPUS = str(uuid4())
DEPT = str(uuid4())
COURSE = str(uuid4())


def _sb():
    sb = FakeDataClient()
    sb.tables["departments"].append({"id": DEPT, "name": "Computer Science"})
    sb.tables["courses"].append({"id": COURSE, "name": "CS and AI"})
    sb.tables["profiles"] += [
        {"id": str(uuid4()), "email": "s1@x.test", "full_name": "S One", "role": "student", "campus_id": CAMPUS,
         "course_id": COURSE, "batch_year": 2025, "section": "A", "created_at": "2026-11-01T00:00:00+00:00"},
        {"id": str(uuid4()), "email": "s2@x.test", "full_name": "S Two", "role": "student", "campus_id": CAMPUS,
         "course_id": None, "batch_year": None, "section": None, "created_at": "2026-11-02T00:00:00+00:00"},
        {"id": str(uuid4()), "email": "f1@x.test", "full_name": "F One", "role": "faculty", "campus_id": CAMPUS,
         "department_id": DEPT, "created_at": "2026-11-03T00:00:00+00:00"},
    ]
    sb.tables["documents"] += [
        {"id": str(uuid4()), "title": "Coding Club rules", "publication_status": "published", "scope": "campus",
         "created_at": "2026-11-05T00:00:00+00:00"},
        {"id": str(uuid4()), "title": "Hostel guide", "publication_status": "archived", "scope": "university_wide",
         "created_at": "2026-11-04T00:00:00+00:00"},
    ]
    sb.tables["announcements"] += [
        {"id": str(uuid4()), "title": "Exam", "category": "Exam", "audience": "all_students", "scope": "campus",
         "is_important": True, "batch_year": None, "section": None, "course_id": None, "created_at": "2026-11-06T00:00:00+00:00"},
        {"id": str(uuid4()), "title": "Staff meeting", "category": "Staff", "audience": "staff_only", "scope": "campus",
         "is_important": False, "created_at": "2026-11-06T01:00:00+00:00"},
    ]
    sb.tables["tickets"] += [
        {"id": str(uuid4()), "ticket_number": "UB-0001", "subject": "Fees", "priority": "high", "status": "resolved",
         "created_at": "2026-11-07T00:00:00+00:00"},
        {"id": str(uuid4()), "ticket_number": "UB-0002", "subject": "Room", "priority": "low", "status": "submitted",
         "created_at": "2026-11-07T01:00:00+00:00"},
    ]
    return sb


def test_counts_come_from_the_rows():
    overview = asyncio.run(management_platform_overview(_sb()))

    assert overview["students"]["total"] == 2
    assert overview["students"]["breakdown"]["course"] == {"CS and AI": 1, "Not set": 1}
    assert overview["students"]["breakdown"]["section"] == {"A": 1, "Not set": 1}
    assert overview["faculty"]["by_department"] == {"Computer Science": 1}
    assert overview["documents"]["by_status"] == {"published": 1, "archived": 1}
    assert overview["documents"]["by_category"] == {"Uncategorised": 2}  # no category column: stated, not invented
    assert overview["announcements"]["by_target"] == {"All Students": 1, "Targeted Academic": 0, "Staff Only": 1}
    assert overview["tickets"]["by_status"]["resolved"] == 1
    assert overview["tickets"]["resolution_rate"] == 0.5
    assert overview["platform"]["by_role"] == {"student": 2, "faculty": 1}


def test_club_lists_hold_only_documents_that_name_a_club():
    overview = asyncio.run(management_platform_overview(_sb()))

    assert overview["clubs"]["active_clubs"] == ["Coding Club"]
    assert [d["title"] for d in overview["clubs"]["initiatives"]] == ["Coding Club rules"]
    assert overview["clubs"]["total_initiatives"] == 1


def test_empty_database_has_no_resolution_rate_and_no_invented_rows():
    empty = asyncio.run(management_platform_overview(FakeDataClient()))

    assert empty["tickets"]["resolution_rate"] is None
    assert empty["students"]["sample"] == [] and empty["announcements"]["recent"] == []
    assert empty["platform"]["total_users"] == 0


def test_route_is_management_only():
    from tests.test_routes import FACULTY_ID, MANAGER_ID, make_profile, _Verifier, FakeProfileRepository
    from app.middleware.auth import get_token_verifier

    sb = _sb()
    profiles = {
        MANAGER_ID: make_profile(MANAGER_ID, role="management", campus_id=CAMPUS),
        FACULTY_ID: make_profile(FACULTY_ID, role="faculty", campus_id=CAMPUS),
    }
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    app.dependency_overrides[get_data_client] = lambda: sb
    try:
        client = TestClient(app)
        ok = client.get("/api/v1/management/overview", headers={"Authorization": f"Bearer {MANAGER_ID}"})
        denied = client.get("/api/v1/management/overview", headers={"Authorization": f"Bearer {FACULTY_ID}"})
    finally:
        app.dependency_overrides.clear()

    assert ok.status_code == 200 and ok.json()["students"]["total"] == 2
    assert denied.status_code == 403
    assert "email" in ok.json()["students"]["sample"][0]  # the directory the Management page already shows
    assert "total;dur=" in ok.headers["Server-Timing"]  # timing header is set on every API response
