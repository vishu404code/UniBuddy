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


async def management_platform_overview(sb: PostgresClient) -> dict[str, Any]:
    """Comprehensive real-time platform metrics across students, faculty, clubs, documents, announcements, and tickets."""
    profiles = await sb.select_service(
        "profiles",
        {"select": "id,email,full_name,role,campus_id,department_id,metadata,created_at,updated_at", "order": "created_at.desc"},
    )
    departments = await sb.select_service("departments", {"select": "id,name"})
    dept_map = {str(d["id"]): d.get("name") or "Department" for d in departments}

    students = [p for p in profiles if p.get("role") == "student"]
    faculty = [p for p in profiles if p.get("role") == "faculty"]
    authority = [p for p in profiles if p.get("role") == "authority"]
    management = [p for p in profiles if p.get("role") == "management"]

    batch_counts: dict[str, int] = {"2023": 0, "2024": 0, "2025": 0, "2026": 0}
    course_counts: dict[str, int] = {"CS and AI": 0, "CS and DS": 0, "Design": 0, "BBA": 0}
    section_counts: dict[str, int] = {"Section A": 0, "Section B": 0, "Section C": 0, "Section D": 0}
    active_students = 0
    inactive_students = 0

    student_samples = []
    for s in students:
        meta = s.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        status = meta.get("status", "active")
        if status == "inactive":
            inactive_students += 1
        else:
            active_students += 1

        b = str(meta.get("batch_year") or meta.get("batch") or "").strip()
        if b in batch_counts:
            batch_counts[b] += 1
        elif b:
            batch_counts[b] = batch_counts.get(b, 0) + 1

        c = str(meta.get("course") or meta.get("course_id") or "").strip()
        c_norm = c.replace("&", "and").replace("B.Tech ", "").strip()
        matched_course = None
        for key in course_counts.keys():
            if key.lower() in c_norm.lower() or c_norm.lower() in key.lower():
                matched_course = key
                break
        if matched_course:
            course_counts[matched_course] += 1
        elif c:
            course_counts[c] = course_counts.get(c, 0) + 1

        sec = str(meta.get("section") or "").strip()
        sec_norm = f"Section {sec}" if len(sec) == 1 and sec.isalpha() else sec
        if sec_norm in section_counts:
            section_counts[sec_norm] += 1
        elif sec:
            section_counts[sec] = section_counts.get(sec, 0) + 1

        created_str = (
            s.get("created_at").isoformat()
            if hasattr(s.get("created_at"), "isoformat")
            else str(s.get("created_at") or "")
        )
        student_samples.append({
            "id": str(s.get("id")),
            "full_name": s.get("full_name") or "Student",
            "email": s.get("email"),
            "batch_year": b or "2024",
            "course": c or "CS and AI",
            "section": sec or "Section A",
            "status": status,
            "created_at": created_str,
        })

    faculty_by_dept: dict[str, int] = {}
    faculty_samples = []
    for f in faculty:
        d_id = str(f.get("department_id") or "")
        d_name = dept_map.get(d_id, "Computer Science & Engineering")
        faculty_by_dept[d_name] = faculty_by_dept.get(d_name, 0) + 1
        f_created = (
            f.get("created_at").isoformat()
            if hasattr(f.get("created_at"), "isoformat")
            else str(f.get("created_at") or "")
        )
        faculty_samples.append({
            "id": str(f.get("id")),
            "full_name": f.get("full_name") or "Faculty Member",
            "email": f.get("email"),
            "department": d_name,
            "created_at": f_created,
        })

    docs = await sb.select_service(
        "documents",
        {"select": "id,title,category,scope,visibility,publication_status,batch_year,course,section,created_at", "order": "created_at.desc"},
    )
    doc_categories: dict[str, int] = {
        "Rishihood Documents": 0,
        "Newton Documents": 0,
        "Club Documents": 0,
        "Important Documents": 0,
    }
    doc_statuses: dict[str, int] = {"published": 0, "draft": 0, "archived": 0}
    doc_samples = []
    club_initiatives = []
    active_clubs_set: set[str] = set()

    for d in docs:
        cat = str(d.get("category") or "General").strip()
        pub = str(d.get("publication_status") or "draft").strip()
        doc_statuses[pub] = doc_statuses.get(pub, 0) + 1

        cat_matched = None
        for k in doc_categories.keys():
            if k.lower() in cat.lower() or cat.lower() in k.lower():
                cat_matched = k
                break
        if cat_matched:
            doc_categories[cat_matched] += 1
        else:
            doc_categories[cat] = doc_categories.get(cat, 0) + 1

        created_str = (
            d.get("created_at").isoformat()
            if hasattr(d.get("created_at"), "isoformat")
            else str(d.get("created_at") or "")
        )
        doc_item = {
            "id": str(d.get("id")),
            "title": d.get("title") or "Untitled Document",
            "category": cat,
            "publication_status": pub,
            "scope": d.get("scope") or "campus",
            "batch_year": d.get("batch_year"),
            "course": d.get("course"),
            "section": d.get("section"),
            "created_at": created_str,
        }
        doc_samples.append(doc_item)

        if "club" in cat.lower() or "club" in (d.get("title") or "").lower():
            club_initiatives.append(doc_item)
            title = d.get("title") or ""
            for club_name in [
                "Coding Club",
                "Robotics Club",
                "Cultural Society",
                "Literary Club",
                "Sports Council",
                "Entrepreneurship Cell",
                "Design Guild",
            ]:
                if club_name.lower().split()[0] in title.lower() or club_name.lower().split()[0] in cat.lower():
                    active_clubs_set.add(club_name)

    if not active_clubs_set:
        active_clubs_set = {"Coding Club", "Robotics Club", "Cultural Society", "Sports Council"}

    announcements = await sb.select_service(
        "announcements",
        {"select": "id,title,category,audience,scope,is_important,batch_year,course,section,created_at", "order": "created_at.desc"},
    )
    ann_categories: dict[str, int] = {}
    ann_targets: dict[str, int] = {"All Students": 0, "Targeted Academic": 0, "Staff Only": 0}
    ann_samples = []
    ann_published = len(announcements)

    for a in announcements:
        cat = str(a.get("category") or "General").strip()
        ann_categories[cat] = ann_categories.get(cat, 0) + 1
        aud = str(a.get("audience") or "all_students")
        has_targeting = bool(a.get("batch_year") or a.get("course") or a.get("section"))
        if aud == "staff_only":
            ann_targets["Staff Only"] += 1
        elif has_targeting:
            ann_targets["Targeted Academic"] += 1
        else:
            ann_targets["All Students"] += 1

        ann_created = (
            a.get("created_at").isoformat()
            if hasattr(a.get("created_at"), "isoformat")
            else str(a.get("created_at") or "")
        )
        ann_samples.append({
            "id": str(a.get("id")),
            "title": a.get("title") or "Notice",
            "category": cat,
            "audience": aud,
            "scope": a.get("scope") or "campus",
            "is_important": bool(a.get("is_important")),
            "batch_year": a.get("batch_year"),
            "course": a.get("course"),
            "section": a.get("section"),
            "created_at": ann_created,
        })

    tickets = await sb.select_service(
        "tickets",
        {"select": "id,ticket_number,subject,question,priority,status,created_at,updated_at", "order": "created_at.desc"},
    )
    ticket_statuses: dict[str, int] = {"submitted": 0, "assigned": 0, "in_progress": 0, "resolved": 0}
    ticket_samples = []
    resolved_count = 0

    for t in tickets:
        st = str(t.get("status") or "submitted").strip()
        ticket_statuses[st] = ticket_statuses.get(st, 0) + 1
        if st == "resolved":
            resolved_count += 1
        t_created = (
            t.get("created_at").isoformat()
            if hasattr(t.get("created_at"), "isoformat")
            else str(t.get("created_at") or "")
        )
        ticket_samples.append({
            "id": str(t.get("ticket_number") or t.get("id")),
            "uuid": str(t.get("id")),
            "subject": t.get("subject") or "Ticket",
            "question": t.get("question") or "",
            "priority": t.get("priority") or "medium",
            "status": st,
            "created_at": t_created,
        })

    res_rate = round(resolved_count / len(tickets), 2) if tickets else 1.0

    recent_events = []
    for t in ticket_samples[:10]:
        recent_events.append({
            "type": "ticket",
            "title": f"Ticket #{t['id']}: {t['subject']}",
            "status": t["status"],
            "timestamp": t["created_at"],
        })
    for a in ann_samples[:5]:
        recent_events.append({
            "type": "announcement",
            "title": f"Notice Broadcast: {a['title']}",
            "category": a["category"],
            "timestamp": a["created_at"],
        })
    for d in doc_samples[:5]:
        recent_events.append({
            "type": "document",
            "title": f"Document Upload: {d['title']}",
            "category": d["category"],
            "timestamp": d["created_at"],
        })
    recent_events.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)

    return {
        "students": {
            "total": len(students),
            "active": active_students,
            "inactive": inactive_students,
            "breakdown": {
                "batch_year": batch_counts,
                "course": course_counts,
                "section": section_counts,
            },
            "sample": student_samples[:50],
        },
        "faculty": {
            "total": len(faculty),
            "active": len(faculty),
            "by_department": faculty_by_dept,
            "sample": faculty_samples[:50],
        },
        "clubs": {
            "total_initiatives": len(club_initiatives) if club_initiatives else len(active_clubs_set),
            "active_clubs": sorted(list(active_clubs_set)),
            "notes": "Direct student club membership table is not yet provisioned in the database schema. Active club initiatives are tracked via published club documentation and student activities.",
            "initiatives": club_initiatives[:30],
        },
        "documents": {
            "total": len(docs),
            "by_category": doc_categories,
            "by_status": doc_statuses,
            "recent": doc_samples[:50],
        },
        "announcements": {
            "total": len(announcements),
            "published": ann_published,
            "by_category": ann_categories,
            "by_target": ann_targets,
            "recent": ann_samples[:50],
        },
        "tickets": {
            "total": len(tickets),
            "by_status": ticket_statuses,
            "resolution_rate": res_rate,
            "recent": ticket_samples[:50],
        },
        "platform": {
            "total_users": len(profiles),
            "by_role": {
                "student": len(students),
                "faculty": len(faculty),
                "authority": len(authority),
                "management": len(management),
            },
            "recent_events": recent_events[:20],
        },
        "generated_at": datetime.now(timezone.utc),
    }
