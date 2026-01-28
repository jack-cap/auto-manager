"""User and Session SQLAlchemy models for authentication."""

from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.company import CompanyConfig


class User(BaseModel):
    """User model for authentication.
    
    Attributes:
        id: UUID primary key (from BaseModel)
        email: Unique email address
        password_hash: Bcrypt hashed password
        name: User's display name
        created_at: Timestamp when user was created (from BaseModel)
        updated_at: Timestamp when user was last updated (from BaseModel)
    """
    
    __tablename__ = "users"
    
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    # Relationships
    sessions: Mapped[List["Session"]] = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    companies: Mapped[List["CompanyConfig"]] = relationship(
        "CompanyConfig",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Session(BaseModel):
    """Session model for refresh token management.
    
    Stores hashed refresh tokens to enable token revocation and
    session management. Each user can have multiple active sessions.
    
    Attributes:
        id: UUID primary key (from BaseModel)
        user_id: Foreign key to users table
        refresh_token_hash: Hashed refresh token for validation
        expires_at: When the refresh token expires
        created_at: Timestamp when session was created (from BaseModel)
    """
    
    __tablename__ = "sessions"
    
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    
    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="sessions",
    )
