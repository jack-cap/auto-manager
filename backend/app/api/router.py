"""Main API router that aggregates all endpoint routers."""

from fastapi import APIRouter

from app.api.endpoints import auth, companies, chat, dashboard, health

# Create main API router
api_router = APIRouter(prefix="/api/v1")

# Include auth router
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# Include companies router
api_router.include_router(companies.router, prefix="/companies", tags=["Companies"])

# Include chat router
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])

# Include dashboard router
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])

# Include health router
api_router.include_router(health.router, tags=["Health"])


@api_router.get("/")
async def api_root():
    """API root endpoint."""
    return {
        "message": "Auto Manager API v1",
        "endpoints": {
            "auth": "/api/v1/auth",
            "companies": "/api/v1/companies",
            "chat": "/api/v1/chat",
            "dashboard": "/api/v1/dashboard",
        },
    }
