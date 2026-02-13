"""Auth endpoint happy path tests."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestAuth:
    """Auth endpoint happy path tests."""

    async def test_register_success(self, client: AsyncClient):
        """User can register with valid credentials."""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "ValidPass123!",
                "full_name": "New User",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert "id" in data

    async def test_login_success(self, client: AsyncClient, db_session):
        """Registered user can login."""
        from sqlalchemy import select

        from app.models.user import User

        # Register first
        await client.post(
            "/api/auth/register",
            json={
                "email": "logintest@example.com",
                "password": "ValidPass123!",
                "full_name": "Login Test",
            },
        )

        # Mark email verified
        result = await db_session.execute(select(User).where(User.email == "logintest@example.com"))
        user = result.scalar_one_or_none()
        if user:
            user.email_verified = True
            await db_session.commit()

        # Login
        response = await client.post(
            "/api/auth/login",
            json={
                "email": "logintest@example.com",
                "password": "ValidPass123!",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_me_returns_user(self, client: AsyncClient, auth_headers: dict):
        """Authenticated user can get their profile."""
        response = await client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
