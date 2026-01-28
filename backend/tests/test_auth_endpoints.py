"""Integration tests for authentication API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
async def setup_database():
    """Set up and tear down test database for each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    """Create async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


class TestRegisterEndpoint:
    """Tests for POST /api/v1/auth/register."""
    
    @pytest.mark.asyncio
    async def test_register_success(self, client):
        """Should create new user and return user info."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "securepassword123",
                "name": "New User",
            },
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["name"] == "New User"
        assert "id" in data
        assert "password" not in data
        assert "password_hash" not in data
    
    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client):
        """Should return 400 for duplicate email."""
        # First registration
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "duplicate@example.com",
                "password": "password123",
                "name": "First User",
            },
        )
        
        # Second registration with same email
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "duplicate@example.com",
                "password": "password456",
                "name": "Second User",
            },
        )
        
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client):
        """Should return 422 for invalid email format."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "not-an-email",
                "password": "password123",
                "name": "Test User",
            },
        )
        
        assert response.status_code == 422


class TestLoginEndpoint:
    """Tests for POST /api/v1/auth/login."""
    
    @pytest.mark.asyncio
    async def test_login_success(self, client):
        """Should return tokens for valid credentials."""
        # Register user first
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "login@example.com",
                "password": "mypassword123",
                "name": "Login User",
            },
        )
        
        # Login
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "login@example.com",
                "password": "mypassword123",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0
    
    @pytest.mark.asyncio
    async def test_login_invalid_email(self, client):
        """Should return 401 for non-existent email."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "anypassword",
            },
        )
        
        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_login_invalid_password(self, client):
        """Should return 401 for wrong password."""
        # Register user first
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "wrongpass@example.com",
                "password": "correctpassword",
                "name": "Test User",
            },
        )
        
        # Login with wrong password
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "wrongpass@example.com",
                "password": "wrongpassword",
            },
        )
        
        assert response.status_code == 401


class TestMeEndpoint:
    """Tests for GET /api/v1/auth/me."""
    
    @pytest.mark.asyncio
    async def test_get_me_authenticated(self, client):
        """Should return user info for authenticated user."""
        # Register and login
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "me@example.com",
                "password": "password123",
                "name": "Me User",
            },
        )
        
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "me@example.com",
                "password": "password123",
            },
        )
        
        access_token = login_response.json()["access_token"]
        
        # Get current user
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "me@example.com"
        assert data["name"] == "Me User"
    
    @pytest.mark.asyncio
    async def test_get_me_unauthenticated(self, client):
        """Should return 403 without token."""
        response = await client.get("/api/v1/auth/me")
        
        assert response.status_code == 403
    
    @pytest.mark.asyncio
    async def test_get_me_invalid_token(self, client):
        """Should return 401 for invalid token."""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        
        assert response.status_code == 401


class TestRefreshEndpoint:
    """Tests for POST /api/v1/auth/refresh."""
    
    @pytest.mark.asyncio
    async def test_refresh_success(self, client):
        """Should return new tokens for valid refresh token."""
        # Register and login
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "refresh@example.com",
                "password": "password123",
                "name": "Refresh User",
            },
        )
        
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "refresh@example.com",
                "password": "password123",
            },
        )
        
        refresh_token = login_response.json()["refresh_token"]
        
        # Refresh tokens
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
    
    @pytest.mark.asyncio
    async def test_refresh_invalid_token(self, client):
        """Should return 401 for invalid refresh token."""
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid-token"},
        )
        
        assert response.status_code == 401


class TestLogoutEndpoint:
    """Tests for POST /api/v1/auth/logout."""
    
    @pytest.mark.asyncio
    async def test_logout_success(self, client):
        """Should invalidate session and return success message."""
        # Register and login
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "logout@example.com",
                "password": "password123",
                "name": "Logout User",
            },
        )
        
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "logout@example.com",
                "password": "password123",
            },
        )
        
        tokens = login_response.json()
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]
        
        # Logout
        response = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        
        assert response.status_code == 200
        assert "Successfully logged out" in response.json()["message"]
        
        # Verify refresh token no longer works
        refresh_response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        
        assert refresh_response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_logout_unauthenticated(self, client):
        """Should return 403 without token."""
        response = await client.post("/api/v1/auth/logout")
        
        assert response.status_code == 403
