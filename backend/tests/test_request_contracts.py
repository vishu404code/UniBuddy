"""Guards against client-chosen identity, role or campus.

Every value that decides who the caller is, what role they have, or which campus they
belong to must come from the verified token and the profiles table. A request body that
accepted one of these fields would let a caller pick their own access. The email in a
provisioning request is the invitee's address, which is the input, not the caller's
identity, so it is not in the forbidden list.
"""

from app.main import app

# campus_id may appear only in the two Super Admin invitation bodies. There, Super Admin picks
# the campus administratively and the database validates it. The invitee never supplies it.
CAMPUS_ALLOWED_PATHS = {"/api/v1/provisioning/authority", "/api/v1/provisioning/management"}

FORBIDDEN_BODY_FIELDS = {
    "role",
    "student_id",
    "uploaded_by",
    "published_by",
    "user_id",
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
            allowed = {"campus_id"} if path in CAMPUS_ALLOWED_PATHS else set()
            leaked = (_body_fields(body, components) & FORBIDDEN_BODY_FIELDS) | (
                (_body_fields(body, components) & {"campus_id"}) - allowed
            )
            if leaked:
                violations.append(f"{method.upper()} {path}: {sorted(leaked)}")
    assert violations == []


def test_identity_writes_under_auth_are_limited_to_the_public_registration_intake():
    openapi = app.openapi()
    writes = sorted(
        f"{method.upper()} {path}"
        for path, operations in openapi["paths"].items()
        for method in operations
        if "/auth/" in path and method != "get"
    )
    assert writes == ["POST /api/v1/auth/registrations"]


def test_campus_is_accepted_in_request_bodies_only_for_super_admin_invitations():
    openapi = app.openapi()
    components = openapi.get("components", {}).get("schemas", {})
    with_campus = sorted(
        f"{method.upper()} {path}"
        for path, operations in openapi["paths"].items()
        for method, operation in operations.items()
        if operation.get("requestBody") and "campus_id" in _body_fields(operation["requestBody"], components)
    )
    assert with_campus == [
        "POST /api/v1/provisioning/authority",
        "POST /api/v1/provisioning/management",
    ]
