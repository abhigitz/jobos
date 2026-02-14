from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
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
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "jane@example.com",
                    "password": "SecurePass123",
                    "full_name": "Jane Doe",
                }
            ]
        }
    )
    email: EmailStr = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., max_length=255)

    @field_validator('email')
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower().strip() if v else v

    @field_validator('password')
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"email": "jane@example.com", "password": "SecurePass123"}
            ]
        }
    )
    email: str
    password: str

    @field_validator('email')
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower().strip() if v else v


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                    "token_type": "bearer",
                    "expires_in": 1800,
                }
            ]
        }
    )
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800


class UserOut(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "email": "jane@example.com",
                    "full_name": "Jane Doe",
                    "is_active": True,
                    "onboarding_completed": False,
                    "telegram_chat_id": None,
                    "email_verified": True,
                }
            ]
        },
    )
    id: UUID
    email: str
    full_name: Optional[str] = None
    is_active: bool
    onboarding_completed: bool
    telegram_chat_id: Optional[int] = None
    email_verified: bool


class VerifyEmailRequest(BaseModel):
    token: str
    email: str


class ResendVerificationRequest(BaseModel):
    email: str

    @field_validator('email')
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower().strip() if v else v


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator('email')
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower().strip() if v else v


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator('new_password')
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class MessageResponse(BaseModel):
    message: str
