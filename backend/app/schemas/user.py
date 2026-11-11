
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    email_verified: bool
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
