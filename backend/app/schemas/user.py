import uuid
from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    model_validator,
)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: str | None = None
    email_verified: bool
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChangePasswordRequest(BaseModel):
    current_password: str

    new_password: str = Field(
        min_length=8,
        max_length=128,
    )

    confirm_password: str

    @model_validator(mode="after")
    def validate_password_confirmation(self):
        if self.new_password != self.confirm_password:
            raise ValueError("New passwords do not match.")

        if self.current_password == self.new_password:
            raise ValueError(
                "New password must be different from current password."
            )

        return self