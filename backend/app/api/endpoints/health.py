"""Health check endpoints with service status.

Provides health check endpoints that report the status of all
dependent services including LMStudio, Ollama, and database.

Validates: Requirements 12.1, 12.2, 12.3
"""

import logging
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services.llm import LLMService
from app.services.ocr import OCRService

logger = logging.getLogger(__name__)

router = APIRouter()


class ServiceStatus(BaseModel):
    """Status of an individual service."""
    available: bool
    message: Optional[str] = None
    latency_ms: Optional[float] = None


class HealthResponse(BaseModel):
    """Health check response with all service statuses."""
    status: str  # "healthy", "degraded", "unhealthy"
    timestamp: str
    version: str
    services: Dict[str, ServiceStatus]


async def check_database(db: AsyncSession) -> ServiceStatus:
    """Check database connectivity."""
    try:
        from sqlalchemy import text
        start = datetime.now()
        await db.execute(text("SELECT 1"))
        latency = (datetime.now() - start).total_seconds() * 1000
        return ServiceStatus(available=True, latency_ms=latency)
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return ServiceStatus(available=False, message=str(e))


async def check_lmstudio() -> ServiceStatus:
    """Check LMStudio connectivity."""
    try:
        ocr_service = OCRService()
        start = datetime.now()
        available = await ocr_service.health_check()
        latency = (datetime.now() - start).total_seconds() * 1000
        await ocr_service.close()
        
        if available:
            return ServiceStatus(available=True, latency_ms=latency)
        else:
            return ServiceStatus(
                available=False,
                message=f"LMStudio not responding at {settings.lmstudio_url}"
            )
    except Exception as e:
        logger.error(f"LMStudio health check failed: {e}")
        return ServiceStatus(
            available=False,
            message=f"Cannot connect to LMStudio: {str(e)}"
        )


async def check_ollama() -> ServiceStatus:
    """Check Ollama connectivity."""
    try:
        llm_service = LLMService()
        start = datetime.now()
        health = await llm_service.health_check()
        latency = (datetime.now() - start).total_seconds() * 1000
        await llm_service.close()
        
        if health.get("ollama", False):
            return ServiceStatus(available=True, latency_ms=latency)
        else:
            return ServiceStatus(
                available=False,
                message=f"Ollama not responding at {settings.ollama_url}"
            )
    except Exception as e:
        logger.error(f"Ollama health check failed: {e}")
        return ServiceStatus(
            available=False,
            message=f"Cannot connect to Ollama: {str(e)}"
        )


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Comprehensive health check endpoint.
    
    Returns the status of all dependent services:
    - Database (SQLite/PostgreSQL)
    - LMStudio (for OCR with chandra model)
    - Ollama (for LLM inference)
    
    Status values:
    - "healthy": All services available
    - "degraded": Some optional services unavailable
    - "unhealthy": Critical services unavailable
    """
    services: Dict[str, ServiceStatus] = {}
    
    # Check database (critical)
    services["database"] = await check_database(db)
    
    # Check LMStudio (optional - for OCR)
    services["lmstudio"] = await check_lmstudio()
    
    # Check Ollama (optional - for LLM)
    services["ollama"] = await check_ollama()
    
    # Determine overall status
    db_available = services["database"].available
    llm_available = services["lmstudio"].available or services["ollama"].available
    
    if db_available and llm_available:
        status = "healthy"
    elif db_available:
        status = "degraded"  # Can function but OCR/LLM unavailable
    else:
        status = "unhealthy"  # Database is critical
    
    return HealthResponse(
        status=status,
        timestamp=datetime.utcnow().isoformat(),
        version="0.1.0",
        services=services,
    )


@router.get("/health/lmstudio", response_model=ServiceStatus)
async def lmstudio_health() -> ServiceStatus:
    """Check LMStudio connectivity specifically.
    
    Use this endpoint to verify LMStudio is running and the
    chandra OCR model is available.
    """
    return await check_lmstudio()


@router.get("/health/ollama", response_model=ServiceStatus)
async def ollama_health() -> ServiceStatus:
    """Check Ollama connectivity specifically.
    
    Use this endpoint to verify Ollama is running and
    models are available for inference.
    """
    return await check_ollama()
