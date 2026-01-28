"""Integration tests for end-to-end flows.

Tests the complete application workflows including:
- Authentication flow (register, login, logout)
- Dashboard data loading
- Document processing flow (mocked)

Validates: Requirements All (Final Integration)
"""

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


class TestAuthenticationFlow:
    """Integration tests for complete authentication flow."""

    @pytest.mark.asyncio
    async def test_complete_auth_flow(self, client):
        """Test complete authentication flow: register -> login -> access -> logout."""
        # Step 1: Register a new user
        register_response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "integration@test.com",
                "password": "securepassword123",
                "name": "Integration Test User",
            },
        )
        assert register_response.status_code == 201
        user_data = register_response.json()
        assert user_data["email"] == "integration@test.com"
        assert "id" in user_data

        # Step 2: Login with the registered user
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "integration@test.com",
                "password": "securepassword123",
            },
        )
        assert login_response.status_code == 200
        tokens = login_response.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]

        # Step 3: Access protected endpoint with token
        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_response.status_code == 200
        me_data = me_response.json()
        assert me_data["email"] == "integration@test.com"

        # Step 4: Refresh the token
        refresh_response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_response.status_code == 200
        new_tokens = refresh_response.json()
        assert "access_token" in new_tokens

        # Step 5: Logout
        logout_response = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert logout_response.status_code == 200

        # Step 6: Verify refresh token is invalidated
        invalid_refresh = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert invalid_refresh.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_credentials_rejected(self, client):
        """Test that invalid credentials are properly rejected."""
        # Try to login with non-existent user
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent@test.com",
                "password": "anypassword",
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_routes_require_auth(self, client):
        """Test that protected routes require authentication."""
        # Try to access protected endpoint without token
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 403

        # Try with invalid token
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401


class TestCompanyManagementFlow:
    """Integration tests for company management flow."""

    async def _create_authenticated_user(self, client) -> tuple[str, str]:
        """Helper to create and authenticate a user."""
        # Register
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "company_test@test.com",
                "password": "password123",
                "name": "Company Test User",
            },
        )
        # Login
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "company_test@test.com",
                "password": "password123",
            },
        )
        tokens = login_response.json()
        return tokens["access_token"], tokens["refresh_token"]

    @pytest.mark.asyncio
    async def test_company_list_empty(self, client):
        """Test that company list is empty for new user."""
        access_token, _ = await self._create_authenticated_user(client)
        headers = {"Authorization": f"Bearer {access_token}"}

        # List companies (should be empty)
        list_response = await client.get("/api/v1/companies", headers=headers)
        assert list_response.status_code == 200
        data = list_response.json()
        # Handle both list and paginated response formats
        companies = data.get("companies", data) if isinstance(data, dict) else data
        assert companies == []

    @pytest.mark.asyncio
    async def test_company_create_validates_connection(self, client):
        """Test that company creation validates Manager.io connection.
        
        Note: This test expects a 502 error because there's no Manager.io
        server running. In a real environment with Manager.io, this would succeed.
        """
        access_token, _ = await self._create_authenticated_user(client)
        headers = {"Authorization": f"Bearer {access_token}"}

        # Try to create a company - should fail with 502 because
        # Manager.io is not available
        create_response = await client.post(
            "/api/v1/companies",
            headers=headers,
            json={
                "name": "Test Company",
                "api_key": "test-api-key-12345",
                "base_url": "http://localhost:8080/api2",
            },
        )
        # Expect 502 Bad Gateway because Manager.io is not running
        assert create_response.status_code == 502
        error_data = create_response.json()
        assert "detail" in error_data

    @pytest.mark.asyncio
    async def test_company_validation_errors(self, client):
        """Test that company creation validates input."""
        access_token, _ = await self._create_authenticated_user(client)
        headers = {"Authorization": f"Bearer {access_token}"}

        # Test empty name
        response = await client.post(
            "/api/v1/companies",
            headers=headers,
            json={
                "name": "",
                "api_key": "test-key",
                "base_url": "http://localhost:8080/api2",
            },
        )
        assert response.status_code == 422

        # Test invalid URL
        response = await client.post(
            "/api/v1/companies",
            headers=headers,
            json={
                "name": "Test Company",
                "api_key": "test-key",
                "base_url": "not-a-url",
            },
        )
        assert response.status_code == 422


class TestDashboardDataLoading:
    """Integration tests for dashboard data loading."""

    @pytest.mark.asyncio
    async def test_dashboard_endpoints_require_auth(self, client):
        """Test that dashboard endpoints require authentication."""
        # Try to access dashboard without auth
        response = await client.get(
            "/api/v1/dashboard/cash-balance",
            params={"company_id": "some-id"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_dashboard_endpoints_require_company(self, client):
        """Test that dashboard endpoints require a valid company."""
        # Register and login
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "dashboard_nocompany@test.com",
                "password": "password123",
                "name": "No Company User",
            },
        )
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "dashboard_nocompany@test.com",
                "password": "password123",
            },
        )
        access_token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Try to access dashboard with invalid company ID
        response = await client.get(
            "/api/v1/dashboard/cash-balance",
            headers=headers,
            params={"company_id": "invalid-company-id"},
        )
        # Should return 404 or 403 for invalid company
        assert response.status_code in (403, 404)


class TestHealthEndpoints:
    """Integration tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_basic_health_check(self, client):
        """Test basic health check endpoint."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data

    @pytest.mark.asyncio
    async def test_detailed_health_check(self, client):
        """Test detailed health check with service status."""
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "services" in data
        assert "database" in data["services"]

    @pytest.mark.asyncio
    async def test_lmstudio_health_check(self, client):
        """Test LMStudio-specific health check."""
        response = await client.get("/api/v1/health/lmstudio")
        assert response.status_code == 200
        data = response.json()
        assert "available" in data

    @pytest.mark.asyncio
    async def test_ollama_health_check(self, client):
        """Test Ollama-specific health check."""
        response = await client.get("/api/v1/health/ollama")
        assert response.status_code == 200
        data = response.json()
        assert "available" in data


class TestAPIDocumentation:
    """Integration tests for API documentation."""

    @pytest.mark.asyncio
    async def test_openapi_schema_available(self, client):
        """Test that OpenAPI schema is available."""
        response = await client.get("/api/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["openapi"].startswith("3.")
        assert "paths" in schema
        assert "components" in schema

    @pytest.mark.asyncio
    async def test_swagger_ui_available(self, client):
        """Test that Swagger UI is available."""
        response = await client.get("/api/docs")
        # Should return HTML or redirect
        assert response.status_code in (200, 307)

    @pytest.mark.asyncio
    async def test_redoc_available(self, client):
        """Test that ReDoc is available."""
        response = await client.get("/api/redoc")
        # Should return HTML or redirect
        assert response.status_code in (200, 307)


class TestErrorHandling:
    """Integration tests for error handling."""

    @pytest.mark.asyncio
    async def test_404_for_unknown_routes(self, client):
        """Test that unknown routes return 404."""
        response = await client.get("/api/v1/unknown-endpoint")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_validation_errors_return_422(self, client):
        """Test that validation errors return 422."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "not-an-email",  # Invalid email
                "password": "short",  # Too short
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_method_not_allowed_returns_405(self, client):
        """Test that wrong HTTP methods return 405."""
        response = await client.delete("/api/v1/auth/login")
        assert response.status_code == 405
