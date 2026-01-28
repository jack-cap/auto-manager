"""Base model classes and mixins for SQLAlchemy models."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def generate_uuid() -> str:
    """Generate a UUID string for primary keys."""
    return str(uuid4())


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamp columns."""
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )


class UUIDPrimaryKeyMixin:
    """Mixin that adds a UUID primary key column."""
    
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )


class BaseModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Base model class with UUID primary key and timestamps.
    
    All application models should inherit from this class.
    
    Example:
        class User(BaseModel):
            __tablename__ = "users"
            
            email: Mapped[str] = mapped_column(String(255), unique=True)
            name: Mapped[str] = mapped_column(String(255))
    """
    
    __abstract__ = True
    
    def to_dict(self) -> dict[str, Any]:
        """Convert model instance to dictionary.
        
        Returns:
            Dictionary representation of the model.
        """
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }
    
    def __repr__(self) -> str:
        """Return string representation of the model."""
        class_name = self.__class__.__name__
        attrs = ", ".join(
            f"{k}={v!r}"
            for k, v in self.to_dict().items()
            if k in ("id", "name", "email")  # Only show key identifying fields
        )
        return f"<{class_name}({attrs})>"
