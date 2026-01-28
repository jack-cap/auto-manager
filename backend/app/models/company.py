"""CompanyConfig SQLAlchemy model for Manager.io company configurations."""

from typing import TYPE_CHECKING, List

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.user import User


class CompanyConfig(BaseModel):
    """Company configuration model for Manager.io API credentials.
    
    Stores per-user company configurations with encrypted API keys.
    Each user can have multiple company configurations.
    
    Attributes:
        id: UUID primary key (from BaseModel)
        user_id: Foreign key to users table
        name: Display name for the company
        base_url: Manager.io API base URL
        api_key_encrypted: Fernet-encrypted API key
        created_at: Timestamp when config was created (from BaseModel)
        updated_at: Timestamp when config was last updated (from BaseModel)
    """
    
    __tablename__ = "company_configs"
    
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    base_url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    api_key_encrypted: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="companies",
    )
