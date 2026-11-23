from datetime import datetime, timezone
from typing import Any

from app.services.postgres_client import PostgresClient

TICKET_STATUSES = ["submitted", "assigned", "in_progress", "resolved"]


async def student_dashboard(sb: PostgresClient, access_token: str) -> dict[str, Any]:
    total_tickets = await sb.count_as_user(access_token, "tickets", {})
    by_status = {}
    for status in TICKET_STATUSES:
        by_status[status] = await sb.count_as_user(access_token, "tickets", {"status": f"eq.{status}"})
    total_questions = await sb.count_as_user(access_token, "messages", {"role": "eq.user"})
    return {
        "total_questions": total_questions,
        "total_tickets": total_tickets,
        "tickets_by_status": by_status,
        "generated_at": datetime.now(timezone.utc),
    }


async def staff_dashboard(sb: PostgresClient, access_token: str) -> dict[str, Any]:
    stats = await sb.rpc_as_user(access_token, "staff_dashboard_stats", {})
    return {**stats, "generated_at": datetime.now(timezone.utc)}


async def management_stats(sb: PostgresClient) -> dict[str, Any]:
    """Aggregates computed in the database. Contains no ticket or student contents."""
    return await sb.rpc_service("management_ticket_stats", {})


async def management_analytics(sb: PostgresClient) -> dict[str, Any]:
    """Aggregates only: question and ticket counts by day, recorded Gemini usage, and ticket totals."""
    activity = await sb.rpc_service("management_activity_stats", {})
    tickets = await sb.rpc_service("management_ticket_stats", {})
    return {**activity, "ticket_totals": tickets}


CLUB_NAMES = ("Coding Club", "Robotics Club", "Cultural Society", "Literary Club", "Sports Council")


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _count_by(rows: list[dict[str, Any]], key: str, default: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get(key) or default)
        counts[label] = counts.get(label, 0) + 1
    return counts


async def management_platform_overview(sb: PostgresClient) -> dict[str, Any]:
    """University-wide counts and recent rows for the Management portal. Management role only (checked by the route).

    Values come from the current schema. Where the schema has no column for a figure, the figure says so:
    documents have no category (counted as 'Uncategorised'), and student status is not stored (all students are active).
    """
    profiles = await sb.select_service(
        "profiles",
        {"select": "id,email,full_name,role,department_id,course_id,batch_year,section,created_at", "order": "created_at.desc"},
    )
    departments = {str(d["id"]): d.get("name") or "Department" for d in await sb.select_service("departments", {"select": "id,name"})}
    courses = {str(c["id"]): c.get("name") or "Course" for c in await sb.select_service("courses", {"select": "id,name"})}

    students = [p for p in profiles if p.get("role") == "student"]
    faculty = [p for p in profiles if p.get("role") == "faculty"]
    by_role = _count_by(profiles, "role", "unknown")

    student_sample = [
        {
            "id": str(s["id"]),
            "full_name": s.get("full_name") or "Student",
            "email": s.get("email"),
            "batch_year": str(s["batch_year"]) if s.get("batch_year") else "Not set",
            "course": courses.get(str(s.get("course_id")), "Not set"),
            "section": s.get("section") or "Not set",
            "status": "active",
            "created_at": _iso(s.get("created_at")),
        }
        for s in students[:50]
    ]
    faculty_sample = [
        {
            "id": str(f["id"]),
            "full_name": f.get("full_name") or "Faculty Member",
            "email": f.get("email"),
            "department": departments.get(str(f.get("department_id")), "Not set"),
            "created_at": _iso(f.get("created_at")),
        }
        for f in faculty[:50]
    ]

    documents = await sb.select_service(
        "documents",
        {"select": "id,title,scope,publication_status,batch_year,section,course_id,created_at", "order": "created_at.desc"},
    )
    doc_recent = [
        {
            "id": str(d["id"]),
            "title": d.get("title") or "Untitled Document",
            "category": "Uncategorised",
            "publication_status": d.get("publication_status") or "draft",
            "scope": d.get("scope") or "campus",
            "batch_year": d.get("batch_year"),
            "section": d.get("section"),
            "course": courses.get(str(d.get("course_id"))),
            "created_at": _iso(d.get("created_at")),
        }
        for d in documents[:50]
    ]
    club_titles = [d for d in documents if any(name.lower() in str(d.get("title") or "").lower() for name in CLUB_NAMES)]
    active_clubs = sorted({name for name in CLUB_NAMES for d in club_titles if name.lower() in str(d.get("title") or "").lower()})

    announcements = await sb.select_service(
        "announcements",
        {"select": "id,title,category,audience,scope,is_important,batch_year,section,course_id,created_at", "order": "created_at.desc"},
    )
    by_target = {"All Students": 0, "Targeted Academic": 0, "Staff Only": 0}
    for a in announcements:
        if a.get("audience") == "staff_only":
            by_target["Staff Only"] += 1
        elif a.get("batch_year") or a.get("section") or a.get("course_id"):
            by_target["Targeted Academic"] += 1
        else:
            by_target["All Students"] += 1
    announcement_recent = [
        {
            "id": str(a["id"]),
            "title": a.get("title") or "Notice",
            "category": a.get("category") or "General",
            "audience": a.get("audience") or "all_students",
            "scope": a.get("scope") or "campus",
            "is_important": bool(a.get("is_important")),
            "created_at": _iso(a.get("created_at")),
        }
        for a in announcements[:20]
    ]

    tickets = await sb.select_service(
        "tickets",
        {"select": "id,ticket_number,subject,question,priority,status,created_at", "order": "created_at.desc"},
    )
    ticket_statuses = {"submitted": 0, "assigned": 0, "in_progress": 0, "resolved": 0}
    for t in tickets:
        status = str(t.get("status") or "submitted")
        ticket_statuses[status] = ticket_statuses.get(status, 0) + 1
    resolved = ticket_statuses.get("resolved", 0)
    ticket_recent = [
        {
            "id": str(t.get("ticket_number") or t["id"]),
            "uuid": str(t["id"]),
            "subject": t.get("subject") or "Ticket",
            "priority": t.get("priority") or "medium",
            "status": t.get("status") or "submitted",
            "created_at": _iso(t.get("created_at")),
        }
        for t in tickets[:20]
    ]

    events = [
        *({"type": "ticket", "title": f"Ticket #{t['id']}: {t['subject']}", "status": t["status"], "timestamp": t["created_at"]} for t in ticket_recent[:8]),
        *({"type": "announcement", "title": f"Notice: {a['title']}", "category": a["category"], "timestamp": a["created_at"]} for a in announcement_recent[:5]),
        *({"type": "document", "title": f"Document: {d['title']}", "category": d["category"], "timestamp": d["created_at"]} for d in doc_recent[:5]),
    ]
    events.sort(key=lambda e: str(e.get("timestamp") or ""), reverse=True)

    return {
        "students": {
            "total": len(students),
            "active": len(students),
            "inactive": 0,
            "breakdown": {
                "batch_year": _count_by(students, "batch_year", "Not set"),
                "course": {courses.get(str(k), "Not set"): v for k, v in _count_by(students, "course_id", "Not set").items()},
                "section": _count_by(students, "section", "Not set"),
            },
            "sample": student_sample,
        },
        "faculty": {
            "total": len(faculty),
            "active": len(faculty),
            "by_department": {departments.get(str(k), "Not set"): v for k, v in _count_by(faculty, "department_id", "Not set").items()},
            "sample": faculty_sample,
        },
        "clubs": {
            "total_initiatives": len(club_titles),
            "active_clubs": active_clubs,
            "notes": "Club membership is not stored. Clubs are listed only where a document title names one.",
            "initiatives": [d for d in doc_recent if any(d["id"] == str(c["id"]) for c in club_titles)][:30],
        },
        "documents": {
            "total": len(documents),
            "by_category": {"Uncategorised": len(documents)},
            "by_status": _count_by(documents, "publication_status", "draft"),
            "recent": doc_recent,
        },
        "announcements": {
            "total": len(announcements),
            "published": len(announcements),
            "by_category": _count_by(announcements, "category", "General"),
            "by_target": by_target,
            "recent": announcement_recent,
        },
        "tickets": {
            "total": len(tickets),
            "by_status": ticket_statuses,
            "resolution_rate": round(resolved / len(tickets), 2) if tickets else None,
            "recent": ticket_recent,
        },
        "platform": {
            "total_users": len(profiles),
            "by_role": by_role,
            "recent_events": events[:20],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
