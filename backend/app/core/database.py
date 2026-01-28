"""Database configuration and session management with async SQLAlchemy."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def create_engine() -> AsyncEngine:
    """Create async database engine based on configuration.
    
    Supports SQLite for development and PostgreSQL for production.
    """
    database_url = settings.database_url
    
    # Configure engine options based on database type
    if database_url.startswith("sqlite"):
        # SQLite-specific configuration
        engine = create_async_engine(
            database_url,
            echo=settings.debug,
            connect_args={"check_same_thread": False},
        )
    else:
        # PostgreSQL configuration
        engine = create_async_engine(
            database_url,
            echo=settings.debug,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
    
    return engine


# Create the async engine
engine = create_engine()

# Create async session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database sessions.
    
    Usage in FastAPI endpoints:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database sessions outside of FastAPI dependencies.
    
    Usage:
        async with get_db_context() as db:
            result = await db.execute(query)
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database by creating all tables.
    
    Should be called on application startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections.
    
    Should be called on application shutdown.
    """
    await engine.dispose()
