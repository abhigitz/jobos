import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings


# bcrypt with 12 rounds (OWASP recommended minimum)
BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def hash_token(token: str) -> str:
    """Hash a token using SHA256 (for refresh tokens, not passwords)."""
    return hashlib.sha256(token.encode()).hexdigest()


def _get_secrets() -> tuple[str, str]:
    settings = get_settings()
    return settings.jwt_secret_key, settings.jwt_refresh_secret_key


def _create_token(data: dict[str, Any], expires_delta: timedelta, secret: str) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret, algorithm="HS256")


def create_access_token(user_id: str) -> str:
    """Create access token with 30 min expiry (security: short-lived to limit exposure)."""
    access_secret, _ = _get_secrets()
    return _create_token(
        {"sub": user_id, "type": "access"},
        timedelta(minutes=30),
        access_secret,
    )


def create_refresh_token(user_id: str) -> str:
    """Create refresh token with 7 day expiry (security: max recommended for refresh tokens)."""
    _, refresh_secret = _get_secrets()
    return _create_token(
        {"sub": user_id, "type": "refresh"},
        timedelta(days=7),
        refresh_secret,
    )


def verify_token(token: str) -> Optional[dict[str, Any]]:
    access_secret, refresh_secret = _get_secrets()
    for secret in (access_secret, refresh_secret):
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            return payload
        except JWTError:
            continue
    return None
