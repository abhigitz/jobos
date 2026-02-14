"""Companies endpoint happy path tests."""
import pytest
from httpx import AsyncClient

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skip(reason="Requires PostgreSQL - SQLite doesn't support ARRAY type"),
]


class TestCompanies:
    """Companies endpoint happy path tests."""

    async def test_create_company(self, client: AsyncClient, auth_headers: dict):
        """User can create a company."""
        response = await client.post(
            "/api/companies",
            json={
                "name": "Acme Corp",
                "lane": 1,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Acme Corp"
        assert data["lane"] == 1

    async def test_list_companies(self, client: AsyncClient, auth_headers: dict):
        """User can list companies."""
        # Create company first
        await client.post(
            "/api/companies",
            json={
                "name": "List Test Corp",
                "lane": 2,
            },
            headers=auth_headers,
        )

        response = await client.get("/api/companies", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    async def test_search_companies(self, client: AsyncClient, auth_headers: dict):
        """User can search companies."""
        # Create company
        await client.post(
            "/api/companies",
            json={
                "name": "Searchable Inc",
                "lane": 1,
            },
            headers=auth_headers,
        )

        response = await client.get(
            "/api/companies/search?q=Searchable",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert "Searchable" in data[0]["name"]

    async def test_quick_create(self, client: AsyncClient, auth_headers: dict):
        """User can quick-create a company."""
        response = await client.post(
            "/api/companies/quick-create",
            json={
                "name": "Quick Corp",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["name"] == "Quick Corp"
