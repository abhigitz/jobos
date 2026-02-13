from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .database import get_db
from .auth.jwt_handler import verify_token
from .config import get_settings
from .models.user import User


def _get_user_id_from_request(request: Request) -> str:
    """Extract user_id from JWT for rate limiting, fallback to IP."""
    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
            user_id = payload.get("sub")
            if user_id:
                return f"user:{user_id}"
        except JWTError:
            pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=_get_user_id_from_request)

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = verify_token(token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User deactivated")

    return user


async def get_current_user_or_n8n(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Accept JWT token OR X-N8N-Secret header."""
    settings = get_settings()

    # Check n8n secret first
    n8n_secret = request.headers.get("X-N8N-Secret")
    if n8n_secret and n8n_secret == settings.n8n_secret and settings.owner_email:
        result = await db.execute(
            select(User).where(User.email == settings.owner_email)
        )
        user = result.scalar_one_or_none()
        if user:
            return user

    # Fall through to JWT auth
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication")
    return await get_current_user(credentials, db)
