"""Tests for backend infrastructure setup."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import (
    Base,
    async_session_factory,
    engine,
    get_db,
    get_db_context,
    init_db,
)
from app.main import app
from app.models.base import BaseModel, generate_uuid


class TestConfig:
    """Tests for application configuration."""

    def test_settings_loaded(self):
        """Test that settings are loaded from environment."""
        assert settings.app_name == "Manager.io Bookkeeper"
        assert settings.database_url is not None
        assert settings.cors_origins is not None

    def test_database_url_format(self):
        """Test that database URL is properly formatted."""
        # Should be either SQLite or PostgreSQL
        assert settings.database_url.startswith(
            ("sqlite", "postgresql")
        ), f"Unexpected database URL format: {settings.database_url}"

    def test_jwt_settings(self):
        """Test JWT configuration is present."""
        assert settings.jwt_algorithm == "HS256"
        assert settings.access_token_expire_minutes > 0
        assert settings.refresh_token_expire_days > 0


class TestDatabase:
    """Tests for database setup and session management."""

    @pytest.fixture(autouse=True)
    async def setup_db(self):
        """Set up test database before each test."""
        await init_db()
        yield
        # Clean up after tests
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def test_database_connection(self):
        """Test that database connection works."""
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1

    async def test_get_db_dependency(self):
        """Test the get_db dependency generator."""
        async for session in get_db():
            assert isinstance(session, AsyncSession)
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1
            break

    async def test_get_db_context_manager(self):
        """Test the get_db_context context manager."""
        async with get_db_context() as session:
            assert isinstance(session, AsyncSession)
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1


class TestBaseModel:
    """Tests for base model functionality."""

    def test_generate_uuid(self):
        """Test UUID generation."""
        uuid1 = generate_uuid()
        uuid2 = generate_uuid()
        
        # UUIDs should be strings
        assert isinstance(uuid1, str)
        assert isinstance(uuid2, str)
        
        # UUIDs should be unique
        assert uuid1 != uuid2
        
        # UUIDs should be 36 characters (standard UUID format)
        assert len(uuid1) == 36
        assert len(uuid2) == 36


class TestAPIEndpoints:
    """Tests for API endpoints."""

    @pytest.fixture
    async def client(self):
        """Create async test client."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    async def test_root_endpoint(self, client: AsyncClient):
        """Test root endpoint returns expected response."""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "docs" in data
        assert "api" in data

    async def test_health_endpoint(self, client: AsyncClient):
        """Test health check endpoint."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data

    async def test_api_v1_root(self, client: AsyncClient):
        """Test API v1 root endpoint."""
        response = await client.get("/api/v1/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "endpoints" in data

    async def test_docs_endpoint(self, client: AsyncClient):
        """Test OpenAPI docs endpoint is accessible."""
        response = await client.get("/api/docs")
        # Should redirect or return HTML
        assert response.status_code in (200, 307)

    async def test_openapi_schema(self, client: AsyncClient):
        """Test OpenAPI schema is generated."""
        response = await client.get("/api/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "info" in data
        assert data["info"]["title"] == "Manager.io Bookkeeper API"


class TestCORS:
    """Tests for CORS configuration."""

    @pytest.fixture
    async def client(self):
        """Create async test client."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    async def test_cors_headers_present(self, client: AsyncClient):
        """Test that CORS headers are present for allowed origins."""
        response = await client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS preflight should succeed
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
