from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth import (
    EmailOTPResend,
    EmailOTPVerify,
    EmailVerificationResponse,
    MessageResponse,
    RegistrationResponse,
    TokenResponse,
    UserLogin,
    UserRegister,
)
from app.services.auth_service import (
    authenticate_user,
    create_user_token,
    register_user,
)
from app.services.otp_service import (
    create_and_send_otp,
    resend_email_otp,
    verify_email_otp,
)

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Authentication"],
)


@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    user_data: UserRegister,
    db: Session = Depends(get_db),
):
    try:
        user = register_user(db, user_data)
        create_and_send_otp(db, user)

        return RegistrationResponse(
            message="Registration successful. Check your email for the verification code.",
            email=user.email,
            email_verified=False,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error


@router.post(
    "/verify-email",
    response_model=EmailVerificationResponse,
)
def verify_email(
    payload: EmailOTPVerify,
    db: Session = Depends(get_db),
):
    try:
        user = verify_email_otp(db, payload.email, payload.otp)
        return EmailVerificationResponse(
            message="Email verified successfully. Your account is now active.",
            email=user.email,
            email_verified=True,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error


@router.post(
    "/resend-otp",
    response_model=MessageResponse,
)
def resend_otp(
    payload: EmailOTPResend,
    db: Session = Depends(get_db),
):
    try:
        resend_email_otp(db, payload.email)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(error),
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    return MessageResponse(
        message="If an unverified account exists for this email, a verification code has been sent."
    )


@router.post(
    "/login",
    response_model=TokenResponse,
)
def login(
    credentials: UserLogin,
    db: Session = Depends(get_db),
):
    user = authenticate_user(
        db,
        credentials.email,
        credentials.password,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password, inactive account, or email not verified.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_user_token(user)
    return TokenResponse(access_token=token)
