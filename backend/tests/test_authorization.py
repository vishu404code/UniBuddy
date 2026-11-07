from uuid import UUID

from app.services.authorization import can_access_campus
from tests.conftest import make_profile

CAMPUS_A = UUID("66666666-6666-6666-6666-666666666666")
CAMPUS_B = UUID("77777777-7777-7777-7777-777777777777")
USER_ID = "88888888-8888-8888-8888-888888888888"


def test_faculty_can_access_own_campus():
    user = make_profile(USER_ID, role="faculty", campus_id=str(CAMPUS_A))

    assert can_access_campus(user, CAMPUS_A) is True


def test_faculty_cannot_access_other_campus():
    user = make_profile(USER_ID, role="faculty", campus_id=str(CAMPUS_A))

    assert can_access_campus(user, CAMPUS_B) is False


def test_authority_is_limited_to_own_campus():
    user = make_profile(USER_ID, role="authority", campus_id=str(CAMPUS_A))

    assert can_access_campus(user, CAMPUS_B) is False


def test_management_without_explicit_grant_is_limited_to_own_campus():
    user = make_profile(USER_ID, role="management", campus_id=str(CAMPUS_A))

    assert can_access_campus(user, CAMPUS_B) is False


def test_management_with_explicit_grant_can_access_any_campus():
    user = make_profile(USER_ID, role="management", campus_id=str(CAMPUS_A), cross_campus_record_access=True)

    assert can_access_campus(user, CAMPUS_B) is True


def test_user_without_campus_cannot_access_any_campus():
    user = make_profile(USER_ID, role="faculty", campus_id=None)

    assert can_access_campus(user, CAMPUS_A) is False
