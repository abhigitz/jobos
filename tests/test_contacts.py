"""Contacts endpoint happy path tests."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestContacts:
    """Contacts endpoint happy path tests."""

    async def test_create_contact(self, client: AsyncClient, auth_headers: dict):
        """User can create a contact."""
        response = await client.post(
            "/api/contacts",
            json={
                "name": "John Doe",
                "company": "TestCorp",
                "their_role": "VP Growth",
                "connection_type": "Direct",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "John Doe"

    async def test_list_contacts(self, client: AsyncClient, auth_headers: dict):
        """User can list contacts."""
        # Create contact first
        await client.post(
            "/api/contacts",
            json={
                "name": "Jane Doe",
                "company": "TestCorp",
                "their_role": "Director",
                "connection_type": "Other",
            },
            headers=auth_headers,
        )

        response = await client.get("/api/contacts", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_update_contact(self, client: AsyncClient, auth_headers: dict):
        """User can update a contact."""
        # Create contact
        create_resp = await client.post(
            "/api/contacts",
            json={
                "name": "Update Test",
                "company": "TestCorp",
                "their_role": "Manager",
                "connection_type": "Direct",
            },
            headers=auth_headers,
        )
        contact_id = create_resp.json()["id"]

        # Update
        response = await client.patch(
            f"/api/contacts/{contact_id}",
            json={"response": "Got a positive reply"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["response"] == "Got a positive reply"
