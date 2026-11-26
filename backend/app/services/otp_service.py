
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.email_otp import EmailOTP
from app.models.user import User
from app.services.email_service import (
    send_otp_email,
    send_password_reset_email,
)


def _create_otp(
    db: Session,
    user: User,
    purpose: str,
    send_email,
) -> None:
    """Invalidate previous codes of the same purpose and send a new OTP."""

    now = datetime.now(timezone.utc)

    existing_codes = db.scalars(
        select(EmailOTP).where(
            EmailOTP.user_id == user.id,
            EmailOTP.purpose == purpose,
            EmailOTP.is_used.is_(False),
        )
    ).all()

    for record in existing_codes:
        record.is_used = True

    otp = f"{secrets.randbelow(1_000_000):06d}"

    record = EmailOTP(
        user_id=user.id,
        otp_hash=hash_password(otp),
        purpose=purpose,
        expires_at=now + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
        attempts=0,
        is_used=False,
    )

    try:
        db.add(record)
        db.commit()
    except Exception:
        db.rollback()
        raise

    send_email(user.email, otp)


def create_and_send_otp(db: Session, user: User) -> None:
    """Create an email-verification OTP."""

    _create_otp(
        db,
        user,
        "email_verification",
        send_otp_email,
    )


def _get_active_otp(
    db: Session,
    user: User,
    purpose: str,
) -> EmailOTP:
    """Retrieve the latest unused OTP for a specific purpose."""

    record = db.scalar(
        select(EmailOTP)
        .where(
            EmailOTP.user_id == user.id,
            EmailOTP.purpose == purpose,
            EmailOTP.is_used.is_(False),
        )
        .order_by(EmailOTP.created_at.desc())
        .limit(1)
        .with_for_update()
    )

    if record is None:
        raise ValueError("No active code. Request a new code.")

    now = datetime.now(timezone.utc)
    expires_at = record.expires_at

    # SQLite may return timezone-naive timestamps.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= now:
        record.is_used = True
        db.commit()
        raise ValueError("Verification code has expired. Request a new code.")

    if record.attempts >= settings.OTP_MAX_ATTEMPTS:
        record.is_used = True
        db.commit()
        raise ValueError(
            "Maximum verification attempts reached. Request a new code."
        )

    return record


def _check_otp(record: EmailOTP, otp: str, db: Session) -> None:
    """Check an OTP and persist failed attempts."""

    record.attempts += 1

    if not verify_password(otp, record.otp_hash):
        if record.attempts >= settings.OTP_MAX_ATTEMPTS:
            record.is_used = True

        db.commit()
        raise ValueError("Invalid email or verification code.")


def verify_email_otp(db: Session, email: str, otp: str) -> User:
    """Verify an email-verification OTP and activate the account."""

    user = db.scalar(
        select(User).where(User.email == email.lower())
    )

    if user is None:
        raise ValueError("Invalid email or verification code.")

    if user.email_verified:
        return user

    record = _get_active_otp(
        db, user, "email_verification"
    )

    _check_otp(record, otp, db)

    record.is_used = True
    user.email_verified = True
    user.is_active = True

    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise

    return user


def resend_email_otp(db: Session, email: str) -> None:
    """Resend an email-verification OTP subject to cooldown."""

    user = db.scalar(
        select(User).where(User.email == email.lower())
    )

    if user is None or user.email_verified:
        return

    latest_record = db.scalar(
        select(EmailOTP)
        .where(
            EmailOTP.user_id == user.id,
            EmailOTP.purpose == "email_verification",
        )
        .order_by(EmailOTP.created_at.desc())
        .limit(1)
    )

    if latest_record is not None:
        now = datetime.now(timezone.utc)
        created_at = latest_record.created_at

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        elapsed = (now - created_at).total_seconds()

        if elapsed < settings.OTP_RESEND_COOLDOWN_SECONDS:
            remaining = int(
                settings.OTP_RESEND_COOLDOWN_SECONDS - elapsed
            ) + 1

            raise ValueError(
                f"Please wait {remaining} seconds before requesting another code."
            )

    create_and_send_otp(db, user)


def request_password_reset(db: Session, email: str) -> None:
    """Request a password-reset OTP without revealing account existence."""

    user = db.scalar(
        select(User).where(User.email == email.lower())
    )

    if user is None or not user.email_verified:
        return

    latest_record = db.scalar(
        select(EmailOTP)
        .where(
            EmailOTP.user_id == user.id,
            EmailOTP.purpose == "password_reset",
        )
        .order_by(EmailOTP.created_at.desc())
        .limit(1)
    )

    if latest_record is not None:
        now = datetime.now(timezone.utc)
        created_at = latest_record.created_at

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        elapsed = (now - created_at).total_seconds()

        if elapsed < settings.OTP_RESEND_COOLDOWN_SECONDS:
            return

    _create_otp(
        db,
        user,
        "password_reset",
        send_password_reset_email,
    )


def reset_password(
    db: Session,
    email: str,
    otp: str,
    new_password: str,
) -> None:
    """Verify a password-reset OTP and save the new password."""

    user = db.scalar(
        select(User).where(User.email == email.lower())
    )

    if user is None or not user.email_verified:
        raise ValueError("Invalid email or verification code.")

    record = _get_active_otp(
        db, user, "password_reset"
    )

    _check_otp(record, otp, db)

    user.password_hash = hash_password(new_password)

    # Invalidate all outstanding password-reset codes for this user.
    outstanding_codes = db.scalars(
        select(EmailOTP).where(
            EmailOTP.user_id == user.id,
            EmailOTP.purpose == "password_reset",
            EmailOTP.is_used.is_(False),
        )
    ).all()

    for code in outstanding_codes:
        code.is_used = True

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
