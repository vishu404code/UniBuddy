"""Guards against client-chosen identity, role or campus.

Every value that decides who a user is, what role they have, or which campus they
belong to must come from the verified token and the profiles table. A request
body that accepted one of these fields would let a caller pick their own access.
"""

from app.main import app

FORBIDDEN_BODY_FIELDS = {
    "role",
    "campus_id",
    "student_id",
    "uploaded_by",
    "published_by",
    "user_id",
    "email",
    "cross_campus_record_access",
    "all_campuses_access",
    "assigned_faculty_id",
    "is_staff",
}


def _resolve(schema: dict, components: dict) -> dict:
    if "$ref" in schema:
        return components[schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def _body_fields(body: dict, components: dict) -> set[str]:
    fields: set[str] = set()
    for media in body.get("content", {}).values():
        schema = _resolve(media.get("schema", {}), components)
        fields.update(schema.get("properties", {}).keys())
    return fields


def test_no_request_body_accepts_role_campus_or_owner_fields():
    openapi = app.openapi()
    components = openapi.get("components", {}).get("schemas", {})
    violations = []
    for path, operations in openapi["paths"].items():
        for method, operation in operations.items():
            body = operation.get("requestBody")
            if not body:
                continue
            leaked = _body_fields(body, components) & FORBIDDEN_BODY_FIELDS
            if leaked:
                violations.append(f"{method.upper()} {path}: {sorted(leaked)}")
    assert violations == []


def test_identity_is_only_read_from_the_profile_endpoint():
    openapi = app.openapi()
    writes = [
        f"{method.upper()} {path}"
        for path, operations in openapi["paths"].items()
        for method in operations
        if "auth" in path and method != "get"
    ]
    assert writes == []
