"""Stage 1 identity rules: Google verifies identity, UniBuddy decides access.

These tests use injected claims and local secrets only. They make no network calls.
"""

from datetime import timedelta
from uuid import UUID, uuid4

import jwt
import pytest

from app.auth.google_identity import GoogleAuthError, GoogleIdentity, identity_from_claims, verify_google_id_token
from app.auth.linking import ProfileRecord, SignInOutcome, build_student_request, decide_sign_in
from app.auth.session import SESSION_AUDIENCE, SESSION_ISSUER, SessionError, issue_session_token, read_session_token

SECRET = "x" * 40
CLIENT_ID = "test-client.apps.googleusercontent.com"


def _claims(**overrides):
    base = {
        "iss": "https://accounts.google.com",
        "sub": "google-subject-1",
        "aud": CLIENT_ID,
        "email": "Student.One@Example.COM",
        "email_verified": True,
        "name": "  Student One ",
    }
    base.update(overrides)
    return base


# --- Google identity -------------------------------------------------------------------

def test_verified_google_account_from_any_domain_is_accepted():
    identity = verify_google_id_token("token", CLIENT_ID, verifier=lambda t, c: _claims())

    assert identity.subject == "google-subject-1"
    assert identity.email == "student.one@example.com"
    assert identity.full_name == "Student One"


def test_gmail_and_university_domains_are_treated_the_same():
    gmail = identity_from_claims(_claims(email="someone@gmail.com"))
    campus = identity_from_claims(_claims(email="someone@nst.rishihood.edu.in"))

    assert gmail.email == "someone@gmail.com"
    assert campus.email == "someone@nst.rishihood.edu.in"


def test_unverified_email_is_refused():
    with pytest.raises(GoogleAuthError, match="not verified"):
        identity_from_claims(_claims(email_verified=False))


def test_string_true_is_not_accepted_as_verified():
    with pytest.raises(GoogleAuthError):
        identity_from_claims(_claims(email_verified="true"))


def test_non_google_issuer_is_refused():
    with pytest.raises(GoogleAuthError, match="issuer"):
        identity_from_claims(_claims(iss="https://evil.example"))


def test_missing_subject_or_email_is_refused():
    with pytest.raises(GoogleAuthError):
        identity_from_claims(_claims(sub=""))
    with pytest.raises(GoogleAuthError):
        identity_from_claims(_claims(email=""))


def test_verifier_failure_is_reported_without_detail():
    def bad(token, client_id):
        raise ValueError("Token audience sk-leaked-detail is wrong")

    with pytest.raises(GoogleAuthError) as info:
        verify_google_id_token("token", CLIENT_ID, verifier=bad)

    assert str(info.value) == "invalid Google token"


def test_missing_token_or_client_id_is_refused_before_verifying():
    with pytest.raises(GoogleAuthError):
        verify_google_id_token("", CLIENT_ID, verifier=lambda t, c: _claims())
    with pytest.raises(GoogleAuthError):
        verify_google_id_token("token", "", verifier=lambda t, c: _claims())


def test_google_claims_never_become_a_role():
    identity = identity_from_claims(_claims(role="super_admin", hd="nst.rishihood.edu.in"))

    assert not hasattr(identity, "role")
    assert set(vars(identity)) == {"subject", "email", "full_name"}


# --- UniBuddy session ------------------------------------------------------------------

def test_session_round_trip_returns_the_user_id():
    user_id = uuid4()
    token = issue_session_token(user_id, SECRET)

    assert read_session_token(token, SECRET) == user_id


def test_session_token_carries_no_role_campus_or_email():
    token = issue_session_token(uuid4(), SECRET)
    payload = jwt.decode(token, SECRET, algorithms=["HS256"], audience=SESSION_AUDIENCE, issuer=SESSION_ISSUER)

    assert set(payload) == {"sub", "iss", "aud", "iat", "exp"}


def test_expired_session_is_refused():
    token = issue_session_token(uuid4(), SECRET, lifetime=timedelta(seconds=-120))

    with pytest.raises(SessionError):
        read_session_token(token, SECRET)


def test_session_signed_with_another_secret_is_refused():
    token = issue_session_token(uuid4(), SECRET)

    with pytest.raises(SessionError):
        read_session_token(token, "y" * 40)


def test_tampered_session_is_refused():
    token = issue_session_token(uuid4(), SECRET)
    header, payload, signature = token.split(".")
    forged_payload = jwt.utils.base64url_encode(
        b'{"sub":"%s","iss":"%s","aud":"%s","iat":1,"exp":9999999999}'
        % (str(uuid4()).encode(), SESSION_ISSUER.encode(), SESSION_AUDIENCE.encode())
    ).decode()

    with pytest.raises(SessionError):
        read_session_token(f"{header}.{forged_payload}.{signature}", SECRET)


def test_session_for_another_audience_is_refused():
    other = jwt.encode(
        {"sub": str(uuid4()), "iss": SESSION_ISSUER, "aud": "someone-else", "iat": 1, "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )

    with pytest.raises(SessionError):
        read_session_token(other, SECRET)


def test_unsigned_session_is_refused():
    unsigned = jwt.encode(
        {"sub": str(uuid4()), "iss": SESSION_ISSUER, "aud": SESSION_AUDIENCE, "iat": 1, "exp": 9999999999},
        key="",
        algorithm="none",
    )

    with pytest.raises(SessionError):
        read_session_token(unsigned, SECRET)


def test_short_secret_is_refused_for_both_issue_and_read():
    with pytest.raises(SessionError):
        issue_session_token(uuid4(), "short")
    with pytest.raises(SessionError):
        read_session_token("a.b.c", "short")


# --- Identity linking ------------------------------------------------------------------

def _identity(subject="google-subject-1", email="person@example.com"):
    return GoogleIdentity(subject=subject, email=email, full_name=None)


def test_known_google_subject_signs_in_to_its_profile():
    profile_id = uuid4()
    decision = decide_sign_in(_identity(), [ProfileRecord(profile_id, "person@example.com", "google-subject-1")])

    assert decision.outcome is SignInOutcome.SIGN_IN
    assert decision.profile_id == profile_id


def test_invited_profile_is_linked_by_exact_verified_email():
    profile_id = uuid4()
    decision = decide_sign_in(_identity(email="Person@Example.com"), [ProfileRecord(profile_id, "person@example.com", None)])

    assert decision.outcome is SignInOutcome.LINK
    assert decision.profile_id == profile_id


def test_existing_authority_profile_keeps_its_id_when_linked():
    authority_id = UUID("2c435f22-6a4b-4128-91ac-b34b62279b44")
    decision = decide_sign_in(
        _identity(subject="new-google-subject", email="yash.g26398@nst.rishihood.edu.in"),
        [ProfileRecord(authority_id, "yash.g26398@nst.rishihood.edu.in", None)],
    )

    assert decision.outcome is SignInOutcome.LINK
    assert decision.profile_id == authority_id


def test_email_already_linked_to_another_google_account_is_a_conflict():
    decision = decide_sign_in(
        _identity(subject="attacker-subject"),
        [ProfileRecord(uuid4(), "person@example.com", "owner-subject")],
    )

    assert decision.outcome is SignInOutcome.CONFLICT
    assert decision.profile_id is None


def test_two_profiles_matching_one_identity_is_a_conflict():
    profiles = [
        ProfileRecord(uuid4(), "person@example.com", None),
        ProfileRecord(uuid4(), "person@example.com", None),
    ]

    assert decide_sign_in(_identity(), profiles).outcome is SignInOutcome.CONFLICT


def test_new_google_account_with_no_profile_gets_no_access():
    decision = decide_sign_in(_identity(email="stranger@gmail.com"), [])

    assert decision.outcome is SignInOutcome.NO_PROFILE
    assert decision.profile_id is None


def test_a_profile_of_any_role_is_never_reported_as_the_decision():
    decision = decide_sign_in(_identity(), [ProfileRecord(uuid4(), "person@example.com", "google-subject-1")])

    assert not hasattr(decision, "role")


# --- Student access requests -----------------------------------------------------------

def test_student_request_is_pending_and_has_only_the_student_role():
    row = build_student_request(_identity(email="new@gmail.com"), pending_subjects=set())

    assert row["status"] == "pending"
    assert row["requested_role"] == "student"
    assert row["email"] == "new@gmail.com"


def test_duplicate_pending_request_is_refused():
    with pytest.raises(ValueError):
        build_student_request(_identity(), pending_subjects={"google-subject-1"})
