"""Jobs endpoint happy path tests."""
import pytest
from httpx import AsyncClient

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skip(reason="Requires PostgreSQL - SQLite doesn't support ARRAY type"),
]


class TestJobs:
    """Jobs endpoint happy path tests."""

    async def test_create_job(self, client: AsyncClient, auth_headers: dict):
        """User can create a job."""
        response = await client.post(
            "/api/jobs",
            json={
                "company_name": "TestCorp",
                "role_title": "Senior Growth Manager",
                "status": "Tracking",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["role_title"] == "Senior Growth Manager"
        assert data["status"] == "Tracking"

    async def test_list_jobs(self, client: AsyncClient, auth_headers: dict):
        """User can list their jobs."""
        # Create a job first
        await client.post(
            "/api/jobs",
            json={
                "company_name": "TestCorp",
                "role_title": "Test Job",
                "status": "Tracking",
            },
            headers=auth_headers,
        )

        response = await client.get("/api/jobs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) >= 1

    async def test_get_pipeline(self, client: AsyncClient, auth_headers: dict):
        """User can get pipeline view."""
        response = await client.get("/api/jobs/pipeline", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Should have all 5 statuses
        assert "Tracking" in data
        assert "Applied" in data
        assert "Interview" in data
        assert "Offer" in data
        assert "Closed" in data

    async def test_update_job_status(self, client: AsyncClient, auth_headers: dict):
        """User can update job status."""
        # Create job
        create_resp = await client.post(
            "/api/jobs",
            json={
                "company_name": "TestCorp",
                "role_title": "Status Test Job",
                "status": "Tracking",
            },
            headers=auth_headers,
        )
        job_id = create_resp.json()["id"]

        # Update status
        response = await client.patch(
            f"/api/jobs/{job_id}",
            json={"status": "Applied"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "Applied"
