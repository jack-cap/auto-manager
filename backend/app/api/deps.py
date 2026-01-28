"""Common dependencies for API endpoints."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

# Type alias for database session dependency
DBSession = Annotated[AsyncSession, Depends(get_db)]


# Re-export authentication dependencies from auth endpoints
# These are defined in auth.py to avoid circular imports
# Usage:
#   from app.api.deps import DBSession
#   from app.api.endpoints.auth import CurrentUser, get_current_user
