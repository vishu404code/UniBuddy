from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.schemas.announcements import AnnouncementCreate
from app.schemas.auth import CurrentUser
from app.schemas.tickets import TicketUpdateRequest
from app.services.announcements import create_announcement
from app.services.dashboards import management_stats, student_dashboard
from app.services.documents import DocumentConflict, DocumentError, DocumentForbidden, DocumentNotFound
from app.services.notifications import mark_notification_read
from app.services.tickets import update_ticket
from tests.fakes import FakeSupabase

CAMPUS = uuid4()
DEPT = uuid4()


def _user(role, campus=CAMPUS):
    return CurrentUser(id=uuid4(), email=f"{role}@example.com", full_name=role, role=role,
                       campus_id=campus, department_id=None)


def _ticket(student, assigned=None, status="submitted", number="UB-0001"):
    ticket_id = uuid4()
    return {
        "id": str(ticket_id), "ticket_number": number, "student_id": str(student.id),
        "campus_id": str(CAMPUS), "department_id": str(DEPT),
        "assigned_faculty_id": str(assigned.id) if assigned else None,
        "subject": "Q", "question": "Q", "description": None, "priority": "medium",
        "status": status, "source_message_id": None,
        "created_at": "2026-11-01T10:00:00+00:00", "updated_at": "2026-11-01T10:00:00+00:00",
    }


def _visible_to_all(token, table, row):
    return True


async def _update(sb, user, ticket_id, **body):
    return await update_ticket(sb=sb, user=user, access_token="t", ticket_id=ticket_id,
                               body=TicketUpdateRequest(**body))


@pytest.mark.asyncio
async def test_faculty_takes_an_unassigned_ticket_and_moves_it_to_assigned():
    faculty, student = _user("faculty"), _user("student")
    sb = FakeSupabase(visible=_visible_to_all)
    ticket = _ticket(student)
    sb.tables["tickets"].append(ticket)

    detail = await _update(sb, faculty, ticket["id"], take_ticket=True)

    assert detail["ticket"]["assigned_faculty_id"] == str(faculty.id)
    assert detail["ticket"]["status"] == "assigned"
    assert [e["event_type"] for e in detail["events"]] == ["assignment"]
    assert sb.tables["notifications"] == []


@pytest.mark.asyncio
async def test_status_change_and_reply_are_recorded_and_notify_the_student():
    faculty, student = _user("faculty"), _user("student")
    sb = FakeSupabase(visible=_visible_to_all)
    ticket = _ticket(student, assigned=faculty, status="assigned")
    sb.tables["tickets"].append(ticket)

    detail = await _update(sb, faculty, ticket["id"], status="in_progress", reply="Checking your marks.")

    assert detail["ticket"]["status"] == "in_progress"
    types = [e["event_type"] for e in detail["events"]]
    assert types == ["status_change", "reply"]
    assert sb.tables["notifications"][0]["user_id"] == str(student.id)


@pytest.mark.asyncio
async def test_faculty_who_is_not_the_assignee_cannot_reply():
    owner, other, student = _user("faculty"), _user("faculty"), _user("student")
    sb = FakeSupabase(visible=_visible_to_all)
    sb.tables["tickets"].append(_ticket(student, assigned=owner, status="assigned"))
    ticket_id = sb.tables["tickets"][0]["id"]

    with pytest.raises(DocumentForbidden):
        await _update(sb, other, ticket_id, reply="hi")


@pytest.mark.asyncio
async def test_status_cannot_move_backwards():
    faculty, student = _user("faculty"), _user("student")
    sb = FakeSupabase(visible=_visible_to_all)
    sb.tables["tickets"].append(_ticket(student, assigned=faculty, status="in_progress"))
    ticket_id = sb.tables["tickets"][0]["id"]

    with pytest.raises(DocumentError, match="cannot move"):
        await _update(sb, faculty, ticket_id, status="assigned")


@pytest.mark.asyncio
async def test_resolved_ticket_is_final():
    faculty, student = _user("faculty"), _user("student")
    sb = FakeSupabase(visible=_visible_to_all)
    sb.tables["tickets"].append(_ticket(student, assigned=faculty, status="resolved"))
    ticket_id = sb.tables["tickets"][0]["id"]

    with pytest.raises(DocumentConflict):
        await _update(sb, faculty, ticket_id, reply="again")


@pytest.mark.asyncio
async def test_ticket_already_taken_by_another_faculty_cannot_be_taken():
    owner, other, student = _user("faculty"), _user("faculty"), _user("student")
    sb = FakeSupabase(visible=_visible_to_all)
    sb.tables["tickets"].append(_ticket(student, assigned=owner, status="assigned"))
    ticket_id = sb.tables["tickets"][0]["id"]

    with pytest.raises(DocumentConflict, match="already assigned"):
        await _update(sb, other, ticket_id, take_ticket=True)


@pytest.mark.asyncio
async def test_concurrent_status_change_is_detected():
    faculty, student = _user("faculty"), _user("student")
    sb = FakeSupabase(visible=_visible_to_all)
    sb.tables["tickets"].append(_ticket(student, assigned=faculty, status="assigned"))
    ticket_id = sb.tables["tickets"][0]["id"]
    original_update = sb.update_service

    async def concurrent_update(table, filters, values):
        for row in sb.tables[table]:
            if row["id"] == ticket_id:
                row["status"] = "in_progress"  # another request moves the ticket after our read
        return await original_update(table, filters, values)

    sb.update_service = concurrent_update

    with pytest.raises(DocumentConflict, match="changed by someone else"):
        await _update(sb, faculty, ticket_id, status="resolved")


@pytest.mark.asyncio
async def test_ticket_outside_visibility_is_not_found():
    student = _user("student")
    sb = FakeSupabase(visible=lambda token, table, row: False)
    sb.tables["tickets"].append(_ticket(student))
    ticket_id = sb.tables["tickets"][0]["id"]

    with pytest.raises(DocumentNotFound):
        await _update(sb, _user("faculty"), ticket_id, take_ticket=True)


@pytest.mark.asyncio
async def test_only_authority_publishes_university_wide_announcements():
    sb = FakeSupabase()
    body = AnnouncementCreate(title="Exams", body="Timetable out.", scope="university_wide")

    with pytest.raises(DocumentForbidden):
        await create_announcement(sb=sb, user=_user("faculty"), body=body)

    created = await create_announcement(sb=sb, user=_user("authority"), body=body)
    assert created["scope"] == "university_wide"
    assert created["campus_id"] is None


@pytest.mark.asyncio
async def test_campus_announcement_is_attributed_to_the_publishers_campus():
    sb = FakeSupabase()
    body = AnnouncementCreate(title="Hostel", body="Water off Friday.", scope="campus", audience="staff_only")

    created = await create_announcement(sb=sb, user=_user("faculty"), body=body)

    assert created["campus_id"] == str(CAMPUS)
    assert created["audience"] == "staff_only"


@pytest.mark.asyncio
async def test_notification_is_marked_read_only_when_visible():
    sb = FakeSupabase(visible=lambda token, table, row: row["user_id"] == me)
    me = str(uuid4())
    note_id = uuid4()
    sb.tables["notifications"].append({"id": str(note_id), "user_id": me, "text": "x", "is_read": False,
                                       "ticket_id": None, "created_at": "2026-11-01T10:00:00+00:00"})

    updated = await mark_notification_read(sb=sb, access_token="t", notification_id=note_id)

    assert updated["is_read"] is True


@pytest.mark.asyncio
async def test_other_users_notification_is_not_found():
    sb = FakeSupabase(visible=lambda token, table, row: False)
    note_id = uuid4()
    sb.tables["notifications"].append({"id": str(note_id), "user_id": str(uuid4()), "text": "x",
                                       "is_read": False, "ticket_id": None,
                                       "created_at": "2026-11-01T10:00:00+00:00"})

    with pytest.raises(DocumentNotFound):
        await mark_notification_read(sb=sb, access_token="t", notification_id=note_id)


@pytest.mark.asyncio
async def test_student_dashboard_counts_only_what_rls_returns():
    student = _user("student")
    sb = FakeSupabase(visible=lambda token, table, row: row.get("student_id", row.get("user_id")) == str(student.id)
                      or table == "messages")
    sb.tables["tickets"] += [_ticket(student, status="resolved", number="UB-1"),
                             _ticket(student, status="submitted", number="UB-2"),
                             _ticket(_user("student"), status="submitted", number="UB-3")]
    sb.tables["messages"] += [{"id": str(uuid4()), "role": "user"}, {"id": str(uuid4()), "role": "user"}]

    stats = await student_dashboard(sb, "t")

    assert stats["total_tickets"] == 2
    assert stats["tickets_by_status"]["resolved"] == 1
    assert stats["tickets_by_status"]["submitted"] == 1
    assert stats["total_questions"] == 2


@pytest.mark.asyncio
async def test_management_stats_compute_rates_and_first_response_time_from_real_rows():
    sb = FakeSupabase()
    campus_name = "Campus One"
    sb.tables["campuses"].append({"id": str(CAMPUS), "name": campus_name})
    sb.tables["departments"].append({"id": str(DEPT), "name": "CS"})
    created = datetime(2026, 11, 1, 10, tzinfo=timezone.utc)
    replied = created + timedelta(hours=5)
    t1, t2 = _ticket(_user("student"), status="resolved", number="UB-1"), _ticket(_user("student"), number="UB-2")
    t1["created_at"], t2["created_at"] = created.isoformat(), created.isoformat()
    sb.tables["tickets"] += [t1, t2]
    sb.tables["ticket_events"].append({"id": str(uuid4()), "ticket_id": t1["id"], "event_type": "reply",
                                       "created_at": replied.isoformat()})

    stats = await management_stats(sb)

    assert stats["total_tickets"] == 2
    assert stats["resolved_tickets"] == 1
    assert stats["resolution_rate"] == 0.5
    assert stats["avg_first_response_hours"] == 5.0
    assert stats["campuses"][0]["name"] == campus_name
    assert stats["campuses"][0]["resolution_rate"] == 0.5
    assert stats["departments"][0]["name"] == "CS"
    assert "student_id" not in str(stats)
