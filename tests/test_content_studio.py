"""Content Studio endpoint happy path tests."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestContentStudio:
    """Content Studio endpoint happy path tests."""

    async def test_get_main_screen(self, client: AsyncClient, auth_headers: dict):
        """User can access content studio main screen."""
        response = await client.get("/api/content-studio", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "topics" in data
        assert "weekly_streak" in data
        assert "story_prompt" in data

    async def test_get_categories(self, client: AsyncClient, auth_headers: dict):
        """User can get content categories."""
        response = await client.get(
            "/api/content-studio/categories",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "all" in data
        assert len(data["all"]) > 0  # Should have preset categories

    async def test_get_history(self, client: AsyncClient, auth_headers: dict):
        """User can get content history."""
        response = await client.get(
            "/api/content-studio/history",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "posts" in data
