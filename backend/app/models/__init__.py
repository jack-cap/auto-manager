"""SQLAlchemy models package.

All models should be imported here to ensure they are registered
with SQLAlchemy's metadata before database initialization.
"""

from app.models.base import BaseModel, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import Session, User
from app.models.company import CompanyConfig
from app.models.conversation import Conversation, ChatMessage, ProcessedDocument

__all__ = [
    "BaseModel",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
    "Session",
    "CompanyConfig",
    "Conversation",
    "ChatMessage",
    "ProcessedDocument",
]
