import os

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-only-secret-key-for-password-reset-tests",
)

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import CITEXT

from app.db.base import Base
from app.models.user import User
from app.models.email_otp import EmailOTP
from app.core.security import verify_password
from app.services import otp_service


# SQLite compatibility for PostgreSQL CITEXT.
@compiles(CITEXT, "sqlite")
def compile_citext_sqlite(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(
        engine,
        tables=[User.__table__, EmailOTP.__table__],
    )

    TestingSession = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    session = TestingSession()

    yield session

    session.close()
    Base.metadata.drop_all(
        engine,
        tables=[EmailOTP.__table__, User.__table__],
    )
    engine.dispose()


@pytest.fixture
def verified_user(db):
    user = User(
        email="lawyer@example.com",
        password_hash=otp_service.hash_password("OldPassword123"),
        display_name="Test Lawyer",
        email_verified=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_password_reset_creates_hashed_otp(
    db, verified_user, monkeypatch
):
    sent = {}

    def fake_send_email(email, otp):
        sent["email"] = email
        sent["otp"] = otp

    monkeypatch.setattr(
        otp_service,
        "send_password_reset_email",
        fake_send_email,
    )

    otp_service.request_password_reset(
        db, "lawyer@example.com"
    )

    record = db.scalar(
        select(EmailOTP).where(
            EmailOTP.user_id == verified_user.id,
            EmailOTP.purpose == "password_reset",
        )
    )

    assert record is not None
    assert record.is_used is False
    assert record.attempts == 0
    assert record.otp_hash != sent["otp"]
    assert verify_password(sent["otp"], record.otp_hash)
    assert sent["email"] == verified_user.email


def test_password_reset_updates_password(
    db, verified_user, monkeypatch
):
    sent = {}

    def fake_send_email(email, otp):
        sent["otp"] = otp

    monkeypatch.setattr(
        otp_service,
        "send_password_reset_email",
        fake_send_email,
    )

    otp_service.request_password_reset(
        db, verified_user.email
    )

    otp_service.reset_password(
        db,
        verified_user.email,
        sent["otp"],
        "NewPassword123",
    )

    db.refresh(verified_user)

    assert verify_password(
        "NewPassword123",
        verified_user.password_hash,
    )
    assert not verify_password(
        "OldPassword123",
        verified_user.password_hash,
    )

    record = db.scalar(
        select(EmailOTP).where(
            EmailOTP.user_id == verified_user.id,
            EmailOTP.purpose == "password_reset",
        )
    )

    assert record.is_used is True


def test_invalid_otp_increments_attempts(
    db, verified_user, monkeypatch
):
    sent = {}

    monkeypatch.setattr(
        otp_service,
        "send_password_reset_email",
        lambda email, otp: sent.update(otp=otp),
    )

    otp_service.request_password_reset(
        db, verified_user.email
    )

    with pytest.raises(ValueError):
        otp_service.reset_password(
            db,
            verified_user.email,
            "000000" if sent["otp"] != "000000" else "111111",
            "NewPassword123",
        )

    record = db.scalar(
        select(EmailOTP).where(
            EmailOTP.user_id == verified_user.id,
            EmailOTP.purpose == "password_reset",
        )
    )

    assert record.attempts == 1
    assert record.is_used is False


def test_expired_otp_is_rejected(
    db, verified_user, monkeypatch
):
    monkeypatch.setattr(
        otp_service,
        "send_password_reset_email",
        lambda email, otp: None,
    )

    otp_service.request_password_reset(
        db, verified_user.email
    )

    record = db.scalar(
        select(EmailOTP).where(
            EmailOTP.user_id == verified_user.id,
            EmailOTP.purpose == "password_reset",
        )
    )

    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    with pytest.raises(ValueError, match="expired"):
        otp_service.reset_password(
            db,
            verified_user.email,
            "123456",
            "NewPassword123",
        )

    db.refresh(record)
    assert record.is_used is True


def test_unverified_user_does_not_receive_reset_otp(
    db, monkeypatch
):
    user = User(
        email="unverified@example.com",
        password_hash=otp_service.hash_password("OldPassword123"),
        display_name="Unverified User",
        email_verified=False,
        is_active=False,
    )
    db.add(user)
    db.commit()

    sent = {"called": False}

    def fake_send_email(email, otp):
        sent["called"] = True

    monkeypatch.setattr(
        otp_service,
        "send_password_reset_email",
        fake_send_email,
    )

    otp_service.request_password_reset(
        db, user.email
    )

    assert sent["called"] is False

    record = db.scalar(
        select(EmailOTP).where(
            EmailOTP.user_id == user.id,
            EmailOTP.purpose == "password_reset",
        )
    )

    assert record is None
