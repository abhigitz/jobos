from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .database import get_db
from .auth.jwt_handler import verify_token
from .config import get_settings
from .models.user import User


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
    if n8n_secret and n8n_secret == settings.n8n_secret:
        result = await db.execute(
            select(User).where(User.email == "abhinav.jain.iitd@gmail.com")
        )
        user = result.scalar_one_or_none()
        if user:
            return user

    # Fall through to JWT auth
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication")
    return await get_current_user(credentials, db)
