"""Database session factory for scheduler tasks.

Scheduler tasks run outside FastAPI's request lifecycle, so they cannot use
Depends(get_db). This provides a standalone async context manager for DB sessions.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal


@asynccontextmanager
async def get_task_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session for use in scheduler tasks."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
