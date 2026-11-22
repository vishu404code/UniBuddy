"""The owner-run assignment tool: dry run by default, blank cells never clear data, the database rules still apply."""

import asyncio
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from tests.fakes import FakeDataClient

_spec = importlib.util.spec_from_file_location(
    "assign_student_academics_tool", Path(__file__).resolve().parents[1] / "tools" / "assign_student_academics.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

CAMPUS = str(uuid4())
OTHER = str(uuid4())


def _profile(sb, email, role, campus=CAMPUS, **academics):
    row = {"id": str(uuid4()), "email": email, "role": role, "campus_id": campus, "batch_year": None,
           "section": None, "course_id": None}
    row.update(academics)
    sb.tables["profiles"].append(row)
    return row


def _world():
    sb = FakeDataClient()
    authority = _profile(sb, "auth@example.test", "authority")
    student = _profile(sb, "stu@example.test", "student")
    course = {"id": str(uuid4()), "campus_id": CAMPUS, "name": "bba", "active": True}
    sb.tables["courses"].append(course)
    sb.tables["courses"].append({"id": str(uuid4()), "campus_id": OTHER, "name": "far", "active": True})
    sb.tables["filter_options"].append({"campus_id": CAMPUS, "kind": "batch", "value": "2026", "active": True})
    sb.tables["filter_options"].append({"campus_id": CAMPUS, "kind": "section", "value": "a", "active": True})
    return sb, authority, student, course


def _rows(**cells):
    row = {"student_email": "stu@example.test", "batch_year": "", "section": "", "course_name": ""}
    row.update(cells)
    return [row]


def test_a_dry_run_plans_the_change_and_writes_nothing():
    sb, authority, student, course = _world()
    planned = asyncio.run(tool.plan(sb, _rows(batch_year="2026", section="a", course_name="bba"), "auth@example.test"))

    assert planned[0].error is None
    assert planned[0].changes == {"batch_year": 2026, "section": "a", "course_id": course["id"]}
    assert student["batch_year"] is None


def test_blank_cells_leave_existing_values_alone():
    sb, authority, student, course = _world()
    student.update(batch_year=2026, section="a", course_id=course["id"])
    planned = asyncio.run(tool.plan(sb, _rows(batch_year="", section="", course_name=""), "auth@example.test"))

    assert planned[0].changes == {}
    written, problems = asyncio.run(tool.apply(sb, planned, "auth@example.test"))
    assert (written, problems) == (0, [])
    assert student["batch_year"] == 2026


def test_clear_removes_a_value_only_when_asked():
    sb, authority, student, course = _world()
    student.update(batch_year=2026, section="a")
    planned = asyncio.run(tool.plan(sb, _rows(batch_year="CLEAR", section="CLEAR"), "auth@example.test"))
    asyncio.run(tool.apply(sb, planned, "auth@example.test"))

    assert student["batch_year"] is None and student["section"] is None


def test_apply_writes_through_the_database_function_and_audits_it():
    sb, authority, student, course = _world()
    planned = asyncio.run(tool.plan(sb, _rows(batch_year="2026", section="a"), "auth@example.test"))
    written, problems = asyncio.run(tool.apply(sb, planned, "auth@example.test"))

    assert (written, problems) == (1, [])
    assert student["batch_year"] == 2026 and student["section"] == "a"
    assert sb.tables["student_academic_audit"][0]["changed_by"] == str(authority["id"])


@pytest.mark.parametrize("cells, message", [
    ({"batch_year": "26"}, "four digits"),
    ({"course_name": "far"}, "not an active course on this campus"),
    ({"course_name": "nonexistent"}, "not an active course on this campus"),
])
def test_bad_values_are_reported_and_not_written(cells, message):
    sb, authority, student, course = _world()
    planned = asyncio.run(tool.plan(sb, _rows(**cells), "auth@example.test"))

    assert message in planned[0].error
    written, problems = asyncio.run(tool.apply(sb, planned, "auth@example.test"))
    assert written == 0 and student["batch_year"] is None


def test_a_non_authority_actor_is_refused():
    sb, authority, student, course = _world()
    _profile(sb, "fac@example.test", "faculty")
    planned = asyncio.run(tool.plan(sb, _rows(batch_year="2026"), "fac@example.test"))

    assert "not Authority" in planned[0].error


def test_an_unknown_student_is_reported():
    sb, authority, student, course = _world()
    rows = [{"student_email": "nobody@example.test", "batch_year": "2026", "section": "", "course_name": ""}]
    planned = asyncio.run(tool.plan(sb, rows, "auth@example.test"))

    assert "no student profile" in planned[0].error
