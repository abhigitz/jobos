from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator
import re


def validate_password_strength(v: str) -> str:
    if len(v) < 8:
        raise ValueError('Password must be at least 8 characters long')
    if not re.search(r'[A-Z]', v):
        raise ValueError('Password must contain at least one uppercase letter')
    if not re.search(r'[0-9]', v):
        raise ValueError('Password must contain at least one number')
    return v


class RegisterRequest(BaseModel):
    email: EmailStr = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., max_length=255)

    @field_validator('password')
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    is_active: bool
    onboarding_completed: bool
    telegram_chat_id: Optional[int] = None
    email_verified: bool

    class Config:
        from_attributes = True


class VerifyEmailRequest(BaseModel):
    token: str
    email: str


class ResendVerificationRequest(BaseModel):
    email: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator('new_password')
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class MessageResponse(BaseModel):
    message: str
