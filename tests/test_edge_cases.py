"""Edge case tests for auth, jobs, companies, and contacts endpoints."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.user import User

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skip(reason="Requires PostgreSQL - SQLite doesn't support ARRAY type"),
]


class TestAuthEdgeCases:
    """Auth endpoint edge case tests."""

    async def test_login_with_wrong_password_returns_401(
        self, client: AsyncClient, db_session
    ):
        """Login with wrong password returns 401."""
        # Register and verify user first
        await client.post(
            "/api/auth/register",
            json={
                "email": "wrongpass@example.com",
                "password": "ValidPass123!",
                "full_name": "Wrong Pass User",
            },
        )
        result = await db_session.execute(
            select(User).where(User.email == "wrongpass@example.com")
        )
        user = result.scalar_one_or_none()
        if user:
            user.email_verified = True
            await db_session.commit()

        response = await client.post(
            "/api/auth/login",
            json={
                "email": "wrongpass@example.com",
                "password": "WrongPassword123!",
            },
        )
        assert response.status_code == 401

    async def test_login_with_nonexistent_email_returns_401(
        self, client: AsyncClient
    ):
        """Login with non-existent email returns 401."""
        response = await client.post(
            "/api/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "SomePass123!",
            },
        )
        assert response.status_code == 401

    async def test_register_with_invalid_email_format_returns_422(
        self, client: AsyncClient
    ):
        """Register with invalid email format returns 422."""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "not-a-valid-email",
                "password": "ValidPass123!",
                "full_name": "Test User",
            },
        )
        assert response.status_code == 422

    async def test_register_with_duplicate_email_returns_400(
        self, client: AsyncClient
    ):
        """Register with duplicate email returns 400."""
        payload = {
            "email": "duplicate@example.com",
            "password": "ValidPass123!",
            "full_name": "First User",
        }
        await client.post("/api/auth/register", json=payload)

        response = await client.post("/api/auth/register", json=payload)
        assert response.status_code == 400

    async def test_access_protected_route_without_token_returns_401(
        self, client: AsyncClient
    ):
        """Access protected route without token returns 401."""
        response = await client.get("/api/auth/me")
        assert response.status_code == 401

    async def test_access_with_expired_invalid_token_returns_401(
        self, client: AsyncClient
    ):
        """Access with expired/invalid token returns 401."""
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid-token-here"},
        )
        assert response.status_code == 401


class TestJobsEdgeCases:
    """Jobs endpoint edge case tests."""

    async def test_create_job_with_missing_required_fields_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Create job with missing required fields returns 422."""
        response = await client.post(
            "/api/jobs",
            json={"status": "Tracking"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_get_nonexistent_job_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Get non-existent job returns 404."""
        response = await client.get(
            "/api/jobs/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_update_job_with_invalid_status_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Update job with invalid status returns 422."""
        create_resp = await client.post(
            "/api/jobs",
            json={
                "company_name": "TestCorp",
                "role_title": "Test Role",
                "status": "Tracking",
            },
            headers=auth_headers,
        )
        job_id = create_resp.json()["id"]

        response = await client.patch(
            f"/api/jobs/{job_id}",
            json={"status": "InvalidStatus"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_analyze_jd_with_empty_text_returns_400(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Analyze JD with empty text returns 400."""
        response = await client.post(
            "/api/jobs/analyze-jd",
            json={"jd_text": ""},
            headers=auth_headers,
        )
        assert response.status_code == 400

    async def test_analyze_jd_with_text_under_50_chars_returns_400(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Analyze JD with text < 50 chars returns 400."""
        response = await client.post(
            "/api/jobs/analyze-jd",
            json={"jd_text": "Short"},
            headers=auth_headers,
        )
        assert response.status_code == 400


class TestCompaniesEdgeCases:
    """Companies endpoint edge case tests."""

    async def test_create_company_with_duplicate_name_returns_409(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Create company with duplicate name returns 409."""
        payload = {"name": "Duplicate Corp", "lane": 1}
        await client.post("/api/companies", json=payload, headers=auth_headers)

        response = await client.post(
            "/api/companies", json=payload, headers=auth_headers
        )
        assert response.status_code == 409

    async def test_get_nonexistent_company_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Get non-existent company returns 404."""
        response = await client.get(
            "/api/companies/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_search_with_empty_query_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Search with empty query fails validation (min_length=2) and returns 422."""
        response = await client.get(
            "/api/companies/search?q=",
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_search_with_no_matches_returns_empty_list(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Search with query that matches nothing returns empty list."""
        response = await client.get(
            "/api/companies/search?q=zz",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data == []


class TestContactsEdgeCases:
    """Contacts endpoint edge case tests."""

    async def test_create_contact_with_missing_required_fields_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Create contact with missing required fields returns 422."""
        response = await client.post(
            "/api/contacts",
            json={
                "company": "TestCorp",
                "connection_type": "Direct",
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_get_nonexistent_contact_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Get non-existent contact returns 404."""
        response = await client.get(
            "/api/contacts/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404
