"""Pytest configuration and fixtures for JobOS tests."""
import os
import asyncio
from typing import AsyncGenerator, Generator

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

# Set test env BEFORE any app imports
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///file:testdb?mode=memory&cache=shared")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-refresh-secret-key-for-testing")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")

# Clear config cache so get_settings picks up test env
from app.config import get_settings

get_settings.cache_clear()

from app.main import app
from app.database import get_db
from app.models.base import Base

# Import all models so Base.metadata has all tables
import app.models  # noqa: F401

TEST_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///file:testdb?mode=memory&cache=shared")

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in TEST_DATABASE_URL else {},
    poolclass=StaticPool if "sqlite" in TEST_DATABASE_URL else None,
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create tables and yield a test database session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test client with overridden database dependency."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def auth_headers(client: AsyncClient, db_session: AsyncSession) -> dict:
    """Register a test user, verify email, and return auth headers."""
    from sqlalchemy import select

    from app.models.user import User

    # Register
    await client.post(
        "/api/auth/register",
        json={
            "email": "test@example.com",
            "password": "TestPass123!",
            "full_name": "Test User",
        },
    )

    # Mark email as verified (login requires verification)
    result = await db_session.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one_or_none()
    if user:
        user.email_verified = True
        await db_session.commit()

    # Login
    response = await client.post(
        "/api/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!",
        },
    )
    token = response.json()["access_token"]

    return {"Authorization": f"Bearer {token}"}
