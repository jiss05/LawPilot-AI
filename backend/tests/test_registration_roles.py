import pytest
from pydantic import ValidationError

from app.schemas.auth import UserRegister


def make_registration(**overrides):
    data = {
        "display_name": "Test User",
        "email": "test@example.com",
        "password": "StrongPassword123",
    }

    data.update(overrides)

    return UserRegister(**data)


def test_client_registration_default_role():
    user = make_registration()

    assert user.requested_role == "CLIENT"
    assert user.professional_id is None


def test_valid_lawyer_registration():
    user = make_registration(
        requested_role="LAWYER",
        professional_id="LAWYER12345",
    )

    assert user.requested_role == "LAWYER"
    assert user.professional_id == "LAWYER12345"


def test_valid_judge_registration():
    user = make_registration(
        requested_role="JUDGE",
        professional_id="JUDGE12345",
    )

    assert user.requested_role == "JUDGE"
    assert user.professional_id == "JUDGE12345"


def test_lawyer_requires_professional_id():
    with pytest.raises(ValidationError):
        make_registration(requested_role="LAWYER")


def test_judge_requires_professional_id():
    with pytest.raises(ValidationError):
        make_registration(requested_role="JUDGE")


def test_invalid_lawyer_id_format():
    with pytest.raises(ValidationError):
        make_registration(
            requested_role="LAWYER",
            professional_id="LAWYER123",
        )


def test_invalid_judge_id_format():
    with pytest.raises(ValidationError):
        make_registration(
            requested_role="JUDGE",
            professional_id="JUDGEABC12",
        )


def test_admin_cannot_self_register():
    with pytest.raises(ValidationError):
        make_registration(requested_role="ADMIN")


def test_client_cannot_provide_professional_id():
    with pytest.raises(ValidationError):
        make_registration(
            requested_role="CLIENT",
            professional_id="LAWYER12345",
        )