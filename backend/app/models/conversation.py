"""Conversation and message models for chat history persistence."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, JSON
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Conversation(BaseModel):
    """Represents a chat conversation session.
    
    Attributes:
        user_id: ID of the user who owns this conversation
        company_id: ID of the company context for this conversation
        title: Optional title for the conversation
        extra_data: Additional metadata (JSON)
    """
    
    __tablename__ = "conversations"
    
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    company_id = Column(String(36), ForeignKey("company_configs.id"), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    extra_data = Column(JSON, nullable=True, default=dict)
    
    # Relationships
    messages = relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan")


class ChatMessage(BaseModel):
    """Represents a single message in a conversation.
    
    Attributes:
        conversation_id: ID of the parent conversation
        role: Message role (user, assistant, system, tool)
        content: Message text content
        tool_calls: JSON array of tool calls made (for assistant messages)
        tool_call_id: ID of the tool call this message responds to (for tool messages)
        extra_data: Additional metadata (JSON)
    """
    
    __tablename__ = "chat_messages"
    
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant, system, tool
    content = Column(Text, nullable=True)
    tool_calls = Column(JSON, nullable=True)  # For assistant messages with tool calls
    tool_call_id = Column(String(100), nullable=True)  # For tool response messages
    extra_data = Column(JSON, nullable=True, default=dict)
    
    # Relationships
    conversation = relationship("Conversation", back_populates="messages")


class ProcessedDocument(BaseModel):
    """Represents a document that has been processed by OCR and the agent.
    
    Attributes:
        conversation_id: ID of the conversation where this document was processed
        user_id: ID of the user who uploaded the document
        company_id: ID of the company context
        filename: Original filename
        document_type: Detected type (receipt, invoice, etc.)
        extracted_text: Raw OCR text
        extracted_data: Structured data extracted by the agent (JSON)
        status: Processing status (pending, processed, submitted, error)
        submission_key: Manager.io entry key if submitted
        error_message: Error message if processing failed
    """
    
    __tablename__ = "processed_documents"
    
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    company_id = Column(String(36), ForeignKey("company_configs.id"), nullable=True, index=True)
    filename = Column(String(255), nullable=True)
    document_type = Column(String(50), nullable=True)  # receipt, invoice, expense_claim, etc.
    extracted_text = Column(Text, nullable=True)
    extracted_data = Column(JSON, nullable=True)  # Structured data from agent
    status = Column(String(20), nullable=False, default="pending")  # pending, processed, submitted, error
    submission_key = Column(String(100), nullable=True)  # Manager.io entry key
    error_message = Column(Text, nullable=True)
