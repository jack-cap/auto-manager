"""Pytest configuration and fixtures for tests.

Provides database fixtures for integration tests using an in-memory SQLite database.
"""

import os
from typing import AsyncGenerator

# Set test environment variables BEFORE any app imports
# This must happen at the top of conftest.py before any other imports
from cryptography.fernet import Fernet
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models.base import BaseModel


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create a test database engine with in-memory SQLite."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    
    yield engine
    
    # Drop all tables after test
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Create a database session for testing.
    
    Each test gets a fresh session with a clean database.
    The session is rolled back after each test to ensure isolation.
    """
    async_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@pytest.fixture(scope="session", autouse=True)
def cleanup_global_engine():
    """Clean up the global database engine after all tests complete.
    
    This is needed because some tests import the global engine from
    app.core.database, which creates a connection pool that needs to
    be disposed of to allow pytest to exit cleanly.
    """
    yield
    # Clean up after all tests
    import asyncio
    from app.core.database import engine as global_engine
    
    async def dispose():
        await global_engine.dispose()
    
    # Run cleanup in the event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(dispose())
        else:
            loop.run_until_complete(dispose())
    except RuntimeError:
        # If no event loop, create one just for cleanup
        asyncio.run(dispose())
