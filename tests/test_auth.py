"""Auth flow unit tests."""
import pytest
from httpx import AsyncClient

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skip(reason="Requires PostgreSQL - SQLite doesn't support ARRAY type"),
]


async def test_register_success(client: AsyncClient, test_user_data: dict):
    """POST /api/v1/auth/register with valid data returns 201 and user data."""
    response = await client.post("/api/v1/auth/register", json=test_user_data)
    assert response.status_code in (200, 201)
    data = response.json()
    assert "id" in data
    assert data.get("email") == test_user_data["email"]
    assert data.get("full_name") == test_user_data["full_name"]


async def test_register_duplicate_email(client: AsyncClient, test_user_data: dict):
    """Register with duplicate email returns 400 or 409."""
    await client.post("/api/v1/auth/register", json=test_user_data)
    response = await client.post("/api/v1/auth/register", json=test_user_data)
    assert response.status_code in (400, 409)


async def test_register_invalid_email(client: AsyncClient):
    """POST /api/v1/auth/register with invalid email format returns 422."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "not-a-valid-email",
            "password": "TestPassword123!",
            "full_name": "Test User",
        },
    )
    assert response.status_code == 422


async def test_login_success(client: AsyncClient, test_user_data: dict):
    """Login with valid credentials returns 200 and access_token."""
    await client.post("/api/v1/auth/register", json=test_user_data)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user_data["email"], "password": test_user_data["password"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


async def test_login_wrong_password(client: AsyncClient, test_user_data: dict):
    """Login with wrong password returns 401."""
    await client.post("/api/v1/auth/register", json=test_user_data)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user_data["email"], "password": "WrongPassword123!"},
    )
    assert response.status_code == 401


async def test_login_nonexistent_user(client: AsyncClient):
    """Login with non-existent email returns 401."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@example.com", "password": "SomePass123!"},
    )
    assert response.status_code == 401


async def test_protected_route_without_token(client: AsyncClient):
    """GET protected route without Authorization header returns 401."""
    response = await client.get("/api/v1/jobs")
    assert response.status_code == 401


async def test_protected_route_with_token(client: AsyncClient, test_user_data: dict):
    """GET protected route with valid token returns 200."""
    await client.post("/api/v1/auth/register", json=test_user_data)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user_data["email"], "password": test_user_data["password"]},
    )
    token = login_response.json()["access_token"]
    response = await client.get(
        "/api/v1/jobs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
