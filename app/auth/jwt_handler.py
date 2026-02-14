import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

logger = logging.getLogger(__name__)


# bcrypt with 12 rounds (OWASP recommended minimum)
BCRYPT_ROUNDS = 12

# bcrypt has a 72-byte limit (Blowfish). bcrypt 5.0+ raises ValueError for longer passwords.
# Truncate to match bcrypt 4.x behavior and ensure compatibility across versions.
BCRYPT_MAX_PASSWORD_BYTES = 72


def _password_bytes(password: str) -> bytes:
    """Encode password to bytes, truncating to 72 bytes for bcrypt compatibility."""
    b = password.encode("utf-8")
    return b[:BCRYPT_MAX_PASSWORD_BYTES] if len(b) > BCRYPT_MAX_PASSWORD_BYTES else b


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash. Returns False on invalid hash format."""
    if not hashed_password or not isinstance(hashed_password, str):
        return False
    # bcrypt hashes are 60 chars, start with $2a$, $2b$, or $2y$
    if len(hashed_password) != 60 or not hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
        return False
    try:
        return bcrypt.checkpw(
            _password_bytes(plain_password),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError) as e:
        # Invalid salt / malformed hash - e.g. bcrypt 5.0 stricter validation, or passlib format
        logger.warning("bcrypt.checkpw failed (hash may be incompatible): %s", e)
        return False


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
