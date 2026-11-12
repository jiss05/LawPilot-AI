from typing import Literal

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


class UserRegister(BaseModel):
    display_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    requested_role: Literal["CLIENT", "LAWYER", "JUDGE"] = "CLIENT"
    professional_id: str | None = Field(default=None, max_length=11)

    @field_validator("professional_id")
    @classmethod
    def normalize_professional_id(cls, value):
        if value is None:
            return None

        return value.strip().upper()

    @model_validator(mode="after")
    def validate_professional_details(self):
        role = self.requested_role
        professional_id = self.professional_id

        if role == "CLIENT":
            if professional_id:
                raise ValueError(
                    "Clients must not provide a professional ID."
                )
            return self

        if not professional_id:
            raise ValueError(
                f"A professional ID is required for {role} registration."
            )

        if role == "LAWYER":
            valid_format = (
                len(professional_id) == 11
                and professional_id.startswith("LAWYER")
                and professional_id[6:].isdigit()
            )
        else:
            valid_format = (
                len(professional_id) == 10
                and professional_id.startswith("JUDGE")
                and professional_id[5:].isdigit()
            )

        if not valid_format:
            raise ValueError(
                f"Invalid {role} ID format."
            )

        return self


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class EmailOTPVerify(BaseModel):
    email: EmailStr
    otp: str = Field(pattern=r"^\d{6}$")


class EmailOTPResend(BaseModel):
    email: EmailStr


class RegistrationResponse(BaseModel):
    message: str
    email: EmailStr
    email_verified: bool = False


class EmailVerificationResponse(BaseModel):
    message: str
    email: EmailStr
    email_verified: bool = True


class MessageResponse(BaseModel):
    message: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"