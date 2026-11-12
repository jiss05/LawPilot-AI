import smtplib
from email.message import EmailMessage

from app.core.config import settings


def send_otp_email(recipient_email: str, otp: str) -> None:
    """Send the email-verification code using the configured SMTP server."""

    if not settings.EMAIL_USERNAME or not settings.EMAIL_PASSWORD:
        raise RuntimeError(
            "SMTP credentials are not configured. Set EMAIL_USERNAME "
            "and EMAIL_PASSWORD in the backend .env file."
        )

    message = EmailMessage()
    message["Subject"] = "LawPilot AI - Verify your email"
    message["From"] = settings.EMAIL_FROM or settings.EMAIL_USERNAME
    message["To"] = recipient_email
    message.set_content(
        "Welcome to LawPilot AI.\n\n"
        f"Your email verification code is: {otp}\n\n"
        f"This code expires in {settings.OTP_EXPIRE_MINUTES} minutes. "
        "Do not share this code with anyone.\n"
    )

    try:
        with smtplib.SMTP(
            settings.EMAIL_HOST,
            settings.EMAIL_PORT,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        ) as smtp:
            if settings.EMAIL_USE_TLS:
                smtp.starttls()
            smtp.login(settings.EMAIL_USERNAME, settings.EMAIL_PASSWORD)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise RuntimeError(
            "The verification email could not be sent. Check SMTP settings and try again."
        ) from error
