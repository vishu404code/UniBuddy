"""Owner-run alternative to the Authority screen: assign student batch, section and course from a verified CSV.

NOT part of the web app, and NOT the Authority portal. It exists because the current portal has no screen for
this. It uses the backend's own data role and the same database function as the API, so the database still
checks that the actor is Authority of the student's campus and that every value is an active option or course.

CSV columns (header required):
  student_email   the student's UniBuddy email (must already have a profile)
  batch_year      e.g. 2026, or blank to leave unchanged, or CLEAR to clear
  section         e.g. a, or blank to leave unchanged, or CLEAR to clear
  course_name     exact name of an active course on the campus, or blank to leave unchanged, or CLEAR to clear

Blank cells never clear data. Dry run by default. Nothing is written without --apply.

  .venv/bin/python tools/assign_student_academics.py --csv verified.csv --actor-email <authority email>
  .venv/bin/python tools/assign_student_academics.py --csv verified.csv --actor-email <authority email> --apply
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CLEAR = "CLEAR"


@dataclass
class Planned:
    row: int
    student_id: str
    changes: dict  # field -> value, or None to clear; only fields that the CSV sets
    error: str | None = None


async def _profile_by_email(sb, email: str):
    rows = await sb.select_service("profiles", {"select": "id,role,campus_id,batch_year,section,course_id",
                                                "email": f"eq.{email.strip().lower()}", "limit": "1"})
    return rows[0] if rows else None


async def _course_on_campus(sb, campus_id: str, name: str):
    rows = await sb.select_service("courses", {"select": "id,active", "campus_id": f"eq.{campus_id}",
                                               "name": f"eq.{name}", "limit": "1"})
    return rows[0] if rows else None


async def plan(sb, rows: list[dict], actor_email: str) -> list[Planned]:
    actor = await _profile_by_email(sb, actor_email)
    planned: list[Planned] = []
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        student = await _profile_by_email(sb, row.get("student_email") or "")
        if not student or student.get("role") != "student":
            planned.append(Planned(number, "", {}, "no student profile with that email"))
            continue
        if not actor or actor.get("role") != "authority" or str(actor.get("campus_id")) != str(student.get("campus_id")):
            planned.append(Planned(number, str(student["id"]), {}, "the actor is not Authority of this student's campus"))
            continue
        changes: dict = {}
        error = None
        batch = (row.get("batch_year") or "").strip()
        section = (row.get("section") or "").strip()
        course = (row.get("course_name") or "").strip()
        if batch.upper() == CLEAR:
            changes["batch_year"] = None
        elif batch:
            if batch.isdigit() and len(batch) == 4:
                changes["batch_year"] = int(batch)
            else:
                error = "batch_year must be four digits, CLEAR, or blank"
        if section:
            changes["section"] = None if section.upper() == CLEAR else section
        if course:
            if course.upper() == CLEAR:
                changes["course_id"] = None
            else:
                match = await _course_on_campus(sb, str(student["campus_id"]), course)
                if not match or not match.get("active", True):
                    error = "course is not an active course on this campus"
                else:
                    changes["course_id"] = str(match["id"])
        planned.append(Planned(number, str(student["id"]), changes, error))
    return planned


async def apply(sb, planned: list[Planned], actor_email: str) -> tuple[int, list[str]]:
    actor = await _profile_by_email(sb, actor_email)
    written, problems = 0, []
    for item in planned:
        if item.error or not item.changes:
            if item.error:
                problems.append(f"row {item.row}: {item.error}")
            continue
        current = await sb.select_service("profiles", {"select": "batch_year,section,course_id",
                                                       "id": f"eq.{item.student_id}", "limit": "1"})
        base = current[0] if current else {}
        values = {
            "batch_year": item.changes.get("batch_year", base.get("batch_year")),
            "section": item.changes.get("section", base.get("section")),
            "course_id": item.changes.get("course_id", base.get("course_id")),
        }
        try:
            await sb.rpc_service("assign_student_academics", {
                "p_student": item.student_id, "p_actor": str(actor["id"]),
                "p_batch_year": values["batch_year"], "p_section": values["section"],
                "p_course_id": str(values["course_id"]) if values["course_id"] else None,
            })
            written += 1
        except Exception as exc:  # noqa: BLE001 - reported per row; the database has already refused the change
            problems.append(f"row {item.row}: {getattr(exc, 'detail', 'refused by the database')}")
    return written, problems


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


async def _main(args) -> int:
    from app.services.providers import build_data_client

    rows = _read(Path(args.csv))
    sb = build_data_client()
    planned = await plan(sb, rows, args.actor_email)
    for item in planned:
        status = item.error or ("nothing to change" if not item.changes else "ready: " + ", ".join(sorted(item.changes)))
        print(f"row {item.row}: {status}")
    if not args.apply:
        print(f"dry run: {sum(1 for p in planned if not p.error and p.changes)} row(s) would change; nothing written")
        return 0
    written, problems = await apply(sb, planned, args.actor_email)
    print(f"written: {written}")
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def main() -> int:
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--actor-email", required=True, help="the Authority account making the change")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
