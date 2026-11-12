import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.email_otp import EmailOTP
from app.models.user import User
from app.services.email_service import send_otp_email


def create_and_send_otp(db: Session, user: User) -> None:
    """Invalidate previous codes, persist a new hashed OTP, then email it."""

    now = datetime.now(timezone.utc)
    existing_codes = db.scalars(
        select(EmailOTP).where(
            EmailOTP.user_id == user.id,
            EmailOTP.is_used.is_(False),
        )
    ).all()

    for record in existing_codes:
        record.is_used = True

    otp = f"{secrets.randbelow(1_000_000):06d}"
    record = EmailOTP(
        user_id=user.id,
        otp_hash=hash_password(otp),
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

    # Keep the pending account and stored OTP if SMTP is temporarily unavailable.
    # The user can request another code through the resend endpoint.
    send_otp_email(user.email, otp)


def verify_email_otp(db: Session, email: str, otp: str) -> User:
    """Verify the latest unused OTP and activate the associated account."""

    user = db.scalar(
        select(User).where(User.email == email.lower())
    )

    if user is None:
        raise ValueError("Invalid email or verification code.")

    if user.email_verified:
        return user

    record = db.scalar(
        select(EmailOTP)
        .where(
            EmailOTP.user_id == user.id,
            EmailOTP.is_used.is_(False),
        )
        .order_by(EmailOTP.created_at.desc())
        .limit(1)
        .with_for_update()
    )

    if record is None:
        raise ValueError("No active verification code. Request a new code.")

    now = datetime.now(timezone.utc)

    if record.expires_at <= now:
        record.is_used = True
        db.commit()
        raise ValueError("Verification code has expired. Request a new code.")

    if record.attempts >= settings.OTP_MAX_ATTEMPTS:
        record.is_used = True
        db.commit()
        raise ValueError("Maximum verification attempts reached. Request a new code.")

    record.attempts += 1

    if not verify_password(otp, record.otp_hash):
        if record.attempts >= settings.OTP_MAX_ATTEMPTS:
            record.is_used = True
        db.commit()
        raise ValueError("Invalid email or verification code.")

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
    """Issue a replacement OTP subject to the resend cooldown."""

    user = db.scalar(
        select(User).where(User.email == email.lower())
    )

    # Use the same response for unknown and already-verified accounts.
    if user is None or user.email_verified:
        return

    latest_record = db.scalar(
        select(EmailOTP)
        .where(EmailOTP.user_id == user.id)
        .order_by(EmailOTP.created_at.desc())
        .limit(1)
    )

    if latest_record is not None:
        now = datetime.now(timezone.utc)
        created_at = latest_record.created_at

        # PostgreSQL returns timezone-aware timestamps. Handle a naive value
        # defensively for test databases or manually-created records.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        elapsed = (now - created_at).total_seconds()
        if elapsed < settings.OTP_RESEND_COOLDOWN_SECONDS:
            remaining = int(settings.OTP_RESEND_COOLDOWN_SECONDS - elapsed) + 1
            raise ValueError(
                f"Please wait {remaining} seconds before requesting another code."
            )

    create_and_send_otp(db, user)
