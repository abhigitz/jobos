from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthSettings:
    def __init__(self) -> None:
        settings = get_settings()
        self.access_secret_key = getattr(settings, "jwt_secret_key")
        self.refresh_secret_key = getattr(settings, "jwt_refresh_secret_key")
        self.access_token_expire_minutes = 30
        self.refresh_token_expire_days = 7


auth_settings = AuthSettings()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _create_token(data: dict[str, Any], expires_delta: timedelta, secret: str) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret, algorithm="HS256")


def create_access_token(user_id: str) -> str:
    return _create_token(
        {"sub": user_id, "type": "access"},
        timedelta(minutes=auth_settings.access_token_expire_minutes),
        auth_settings.access_secret_key,
    )


def create_refresh_token(user_id: str) -> str:
    return _create_token(
        {"sub": user_id, "type": "refresh"},
        timedelta(days=auth_settings.refresh_token_expire_days),
        auth_settings.refresh_secret_key,
    )


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    try:
        payload = jwt.decode(token, auth_settings.access_secret_key, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def decode_refresh_token(token: str) -> Optional[dict[str, Any]]:
    try:
        payload = jwt.decode(token, auth_settings.refresh_secret_key, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            return None
        return payload
    except JWTError:
        return None
