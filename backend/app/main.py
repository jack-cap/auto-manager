"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.logging import get_logger, setup_logging

# Set up logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown events."""
    # Startup
    logger.info("Starting Manager.io Bookkeeper API")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Database URL: {settings.database_url.split('@')[-1] if '@' in settings.database_url else settings.database_url}")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Manager.io Bookkeeper API")
    await close_db()
    logger.info("Database connections closed")


app = FastAPI(
    title="Manager.io Bookkeeper API",
    description="AI-powered bookkeeping automation for Manager.io",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "debug": settings.debug,
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Manager.io Bookkeeper API",
        "docs": "/api/docs",
        "api": "/api/v1",
    }
