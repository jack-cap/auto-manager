"""Application configuration using Pydantic Settings."""

import os
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "Manager.io Bookkeeper"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # Database
    database_url: str = "sqlite+aiosqlite:///./automanager.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl: int = 300  # 5 minutes

    # CORS
    cors_origins: List[str] = ["http://localhost:3000"]

    # JWT
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # LLM Configuration
    lmstudio_url: str = "http://localhost:1234/v1"
    ollama_url: str = "http://localhost:11434"
    default_llm_provider: str = "ollama"
    default_llm_model: str = "llama3"
    ocr_model: str = "chandra"

    # Encryption - empty string means not configured
    # For testing, set ENCRYPTION_KEY environment variable
    encryption_key: str = ""


# Create settings instance
settings = Settings()
