"""LLM Service using LiteLLM for unified model routing.

This module provides the LLMService class for interacting with various
LLM providers through a unified interface using LiteLLM.

Features:
- Unified interface for local (Ollama/LMStudio) and cloud providers
- Model routing based on configuration
- Fallback logic for unavailable models
- Vision model support for document analysis
- Health checks for provider connectivity
"""

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import httpx
import litellm
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

# Configure LiteLLM
litellm.set_verbose = False  # Disable verbose logging by default


# =============================================================================
# Enums and Constants
# =============================================================================


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"


# Provider-specific API base URLs
PROVIDER_URLS = {
    LLMProvider.OLLAMA: "http://localhost:11434",
    LLMProvider.LMSTUDIO: "http://localhost:1234/v1",
}


# =============================================================================
# Data Models
# =============================================================================


class Message(BaseModel):
    """Chat message model."""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class ModelInfo:
    """Information about an available model.
    
    Attributes:
        id: Model identifier
        name: Human-readable model name
        provider: LLM provider (ollama, lmstudio, openai, etc.)
        supports_vision: Whether the model supports vision/image inputs
        context_length: Maximum context length in tokens
        parameters: Additional model parameters
    """
    id: str
    name: str
    provider: str
    supports_vision: bool = False
    context_length: Optional[int] = None
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMConfig:
    """Configuration for LLM service.
    
    Attributes:
        default_provider: Default LLM provider to use
        default_model: Default model name
        ollama_url: Ollama API base URL
        lmstudio_url: LMStudio API base URL
        openai_api_key: OpenAI API key (optional)
        anthropic_api_key: Anthropic API key (optional)
        azure_api_key: Azure OpenAI API key (optional)
        azure_api_base: Azure OpenAI API base URL (optional)
        fallback_models: List of fallback models in priority order
        timeout: Request timeout in seconds
        max_retries: Maximum number of retries for failed requests
    """
    default_provider: str = "ollama"
    default_model: str = "llama3"
    ollama_url: str = "http://localhost:11434"
    lmstudio_url: str = "http://localhost:1234/v1"
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    azure_api_key: Optional[str] = None
    azure_api_base: Optional[str] = None
    fallback_models: List[str] = field(default_factory=lambda: ["ollama/llama3", "ollama/mistral"])
    timeout: float = 120.0
    max_retries: int = 3


# =============================================================================
# Exceptions
# =============================================================================


class LLMError(Exception):
    """Base exception for LLM errors."""
    pass


class LLMConnectionError(LLMError):
    """Raised when connection to LLM provider fails."""
    pass


class LLMModelNotFoundError(LLMError):
    """Raised when the requested model is not available."""
    pass


class LLMProviderError(LLMError):
    """Raised when the LLM provider returns an error."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when LLM request times out."""
    pass


# =============================================================================
# LLM Service
# =============================================================================


class LLMService:
    """Service for LLM interactions using LiteLLM.
    
    Provides a unified interface for interacting with various LLM providers
    including local (Ollama, LMStudio) and cloud (OpenAI, Anthropic) providers.
    
    Features:
    - Automatic model routing based on provider prefix
    - Fallback logic for unavailable models
    - Vision model support for document analysis
    - Health checks for provider connectivity
    
    Example:
        ```python
        config = LLMConfig(
            default_provider="ollama",
            default_model="llama3",
            ollama_url="http://localhost:11434",
        )
        
        llm = LLMService(config)
        
        # Check connectivity
        health = await llm.health_check()
        if health.get("ollama"):
            # Chat with the model
            messages = [Message(role="user", content="Hello!")]
            response = await llm.chat(messages)
            print(response)
        ```
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        """Initialize LLMService.
        
        Args:
            config: LLM configuration. If None, uses settings from config.py.
        """
        if config is None:
            config = LLMConfig(
                default_provider=settings.default_llm_provider,
                default_model=settings.default_llm_model,
                ollama_url=settings.ollama_url,
                lmstudio_url=settings.lmstudio_url,
            )
        
        self.config = config
        self._http_client: Optional[httpx.AsyncClient] = None
        
        # Configure LiteLLM with provider URLs
        self._configure_litellm()
    
    def _configure_litellm(self) -> None:
        """Configure LiteLLM with provider-specific settings."""
        # Set API keys if available
        if self.config.openai_api_key:
            litellm.openai_key = self.config.openai_api_key
        
        if self.config.anthropic_api_key:
            litellm.anthropic_key = self.config.anthropic_api_key
        
        if self.config.azure_api_key:
            litellm.azure_key = self.config.azure_api_key
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.
        
        Returns:
            Configured httpx.AsyncClient instance
        """
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
            )
        return self._http_client
    
    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
    
    async def __aenter__(self) -> "LLMService":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
    
    # =========================================================================
    # Model Resolution
    # =========================================================================
    
    def _resolve_model(self, model: Optional[str] = None) -> str:
        """Resolve model name to LiteLLM format.
        
        LiteLLM uses provider prefixes for routing:
        - ollama/llama3 -> Ollama
        - openai/gpt-4 -> OpenAI
        - anthropic/claude-3 -> Anthropic
        
        Args:
            model: Model name (with or without provider prefix)
            
        Returns:
            Model name in LiteLLM format (provider/model)
        """
        if model is None:
            model = self.config.default_model
        
        # If model already has provider prefix, return as-is
        if "/" in model:
            return model
        
        # Add default provider prefix
        provider = self.config.default_provider.lower()
        
        # Map provider to LiteLLM prefix
        if provider == "lmstudio":
            # LMStudio uses OpenAI-compatible API
            return f"openai/{model}"
        elif provider in ["ollama", "openai", "anthropic", "azure"]:
            return f"{provider}/{model}"
        else:
            # Default to ollama for unknown providers
            return f"ollama/{model}"
    
    def _get_api_base(self, model: str) -> Optional[str]:
        """Get API base URL for a model.
        
        Args:
            model: Model name in LiteLLM format (provider/model)
            
        Returns:
            API base URL or None for cloud providers
        """
        if model.startswith("ollama/"):
            return self.config.ollama_url
        elif model.startswith("openai/") and self.config.default_provider == "lmstudio":
            # LMStudio uses OpenAI-compatible API
            return self.config.lmstudio_url
        elif model.startswith("azure/"):
            return self.config.azure_api_base
        
        # Cloud providers use default URLs
        return None
    
    # =========================================================================
    # Chat Methods
    # =========================================================================
    
    async def chat(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Send a chat request to the LLM.
        
        Args:
            messages: List of chat messages
            model: Model name (optional, uses default if not specified)
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens in response (optional)
            
        Returns:
            Model response text
            
        Raises:
            LLMConnectionError: If connection to provider fails
            LLMModelNotFoundError: If model is not available
            LLMProviderError: If provider returns an error
            LLMTimeoutError: If request times out
        """
        resolved_model = self._resolve_model(model)
        api_base = self._get_api_base(resolved_model)
        
        # Convert messages to LiteLLM format
        litellm_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]
        
        # Try primary model, then fallbacks
        models_to_try = [resolved_model] + self.config.fallback_models
        last_error: Optional[Exception] = None
        
        for attempt_model in models_to_try:
            try:
                return await self._call_litellm(
                    model=attempt_model,
                    messages=litellm_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_base=self._get_api_base(attempt_model),
                )
            except (LLMConnectionError, LLMModelNotFoundError) as e:
                logger.warning(
                    f"Model {attempt_model} unavailable, trying fallback: {e}"
                )
                last_error = e
                continue
            except LLMError:
                raise
        
        # All models failed
        if last_error:
            raise last_error
        raise LLMError("All models failed")
    
    async def chat_with_vision(
        self,
        messages: List[Message],
        images: List[bytes],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Send a chat request with images to a vision-capable LLM.
        
        Args:
            messages: List of chat messages
            images: List of image bytes to include
            model: Vision model name (optional)
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens in response (optional)
            
        Returns:
            Model response text
            
        Raises:
            LLMConnectionError: If connection to provider fails
            LLMModelNotFoundError: If model is not available
            LLMProviderError: If provider returns an error
            LLMTimeoutError: If request times out
        """
        resolved_model = self._resolve_model(model)
        api_base = self._get_api_base(resolved_model)
        
        # Build messages with images
        litellm_messages = []
        
        for msg in messages:
            if msg.role == "user" and images:
                # Add images to user message
                content = [{"type": "text", "text": msg.content}]
                
                for image_data in images:
                    base64_image = base64.b64encode(image_data).decode("utf-8")
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    })
                
                litellm_messages.append({"role": msg.role, "content": content})
            else:
                litellm_messages.append({"role": msg.role, "content": msg.content})
        
        # Try primary model, then fallbacks (filter for vision-capable models)
        models_to_try = [resolved_model]
        last_error: Optional[Exception] = None
        
        for attempt_model in models_to_try:
            try:
                return await self._call_litellm(
                    model=attempt_model,
                    messages=litellm_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_base=self._get_api_base(attempt_model),
                )
            except (LLMConnectionError, LLMModelNotFoundError) as e:
                logger.warning(
                    f"Vision model {attempt_model} unavailable: {e}"
                )
                last_error = e
                continue
            except LLMError:
                raise
        
        # All models failed
        if last_error:
            raise last_error
        raise LLMError("All vision models failed")
    
    async def _call_litellm(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        api_base: Optional[str] = None,
    ) -> str:
        """Make a call to LiteLLM.
        
        Args:
            model: Model name in LiteLLM format
            messages: Messages in LiteLLM format
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            api_base: Optional API base URL
            
        Returns:
            Model response text
            
        Raises:
            LLMConnectionError: If connection fails
            LLMModelNotFoundError: If model not found
            LLMProviderError: If provider returns error
            LLMTimeoutError: If request times out
        """
        try:
            # Build kwargs for litellm
            kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "timeout": self.config.timeout,
            }
            
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            
            if api_base:
                kwargs["api_base"] = api_base
            
            # Make async call to LiteLLM
            response = await litellm.acompletion(**kwargs)
            
            # Extract response text
            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content or ""
            
            return ""
            
        except litellm.exceptions.AuthenticationError as e:
            raise LLMProviderError(f"Authentication failed: {e}")
        except litellm.exceptions.NotFoundError as e:
            raise LLMModelNotFoundError(f"Model not found: {e}")
        except litellm.exceptions.RateLimitError as e:
            raise LLMProviderError(f"Rate limited: {e}")
        except litellm.exceptions.APIConnectionError as e:
            raise LLMConnectionError(f"Connection failed: {e}")
        except litellm.exceptions.Timeout as e:
            raise LLMTimeoutError(f"Request timed out: {e}")
        except litellm.exceptions.APIError as e:
            raise LLMProviderError(f"API error: {e}")
        except asyncio.TimeoutError:
            raise LLMTimeoutError(f"Request timed out after {self.config.timeout}s")
        except Exception as e:
            # Log unexpected errors
            logger.error(f"Unexpected LLM error: {e}")
            raise LLMError(f"LLM request failed: {e}")
    
    # =========================================================================
    # Model Discovery
    # =========================================================================
    
    async def list_available_models(self) -> List[ModelInfo]:
        """List all available models from configured providers.
        
        Queries Ollama and LMStudio for installed models.
        
        Returns:
            List of ModelInfo objects for available models
        """
        models: List[ModelInfo] = []
        
        # Query Ollama
        ollama_models = await self._list_ollama_models()
        models.extend(ollama_models)
        
        # Query LMStudio
        lmstudio_models = await self._list_lmstudio_models()
        models.extend(lmstudio_models)
        
        return models
    
    async def _list_ollama_models(self) -> List[ModelInfo]:
        """List models available in Ollama.
        
        Returns:
            List of ModelInfo objects for Ollama models
        """
        try:
            client = await self._get_http_client()
            response = await client.get(f"{self.config.ollama_url}/api/tags")
            
            if response.status_code != 200:
                logger.warning(f"Ollama returned status {response.status_code}")
                return []
            
            data = response.json()
            models = data.get("models", [])
            
            return [
                ModelInfo(
                    id=f"ollama/{model.get('name', '')}",
                    name=model.get("name", ""),
                    provider="ollama",
                    supports_vision=self._is_vision_model(model.get("name", "")),
                    parameters=model.get("details", {}),
                )
                for model in models
            ]
            
        except httpx.ConnectError:
            logger.debug(f"Cannot connect to Ollama at {self.config.ollama_url}")
            return []
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
            return []
    
    async def _list_lmstudio_models(self) -> List[ModelInfo]:
        """List models available in LMStudio.
        
        Returns:
            List of ModelInfo objects for LMStudio models
        """
        try:
            client = await self._get_http_client()
            response = await client.get(f"{self.config.lmstudio_url}/models")
            
            if response.status_code != 200:
                logger.warning(f"LMStudio returned status {response.status_code}")
                return []
            
            data = response.json()
            models = data.get("data", [])
            
            return [
                ModelInfo(
                    id=f"lmstudio/{model.get('id', '')}",
                    name=model.get("id", ""),
                    provider="lmstudio",
                    supports_vision=self._is_vision_model(model.get("id", "")),
                )
                for model in models
            ]
            
        except httpx.ConnectError:
            logger.debug(f"Cannot connect to LMStudio at {self.config.lmstudio_url}")
            return []
        except Exception as e:
            logger.warning(f"Failed to list LMStudio models: {e}")
            return []
    
    def _is_vision_model(self, model_name: str) -> bool:
        """Check if a model supports vision based on its name.
        
        Args:
            model_name: Model name to check
            
        Returns:
            True if model likely supports vision
        """
        vision_keywords = [
            "vision", "llava", "bakllava", "chandra",
            "gpt-4-vision", "gpt-4o", "claude-3",
            "gemini-pro-vision", "moondream",
        ]
        
        model_lower = model_name.lower()
        return any(keyword in model_lower for keyword in vision_keywords)
    
    # =========================================================================
    # Health Check
    # =========================================================================
    
    async def health_check(self) -> Dict[str, bool]:
        """Check connectivity to all configured providers.
        
        Returns:
            Dictionary mapping provider names to connectivity status
        """
        health: Dict[str, bool] = {}
        
        # Check Ollama
        health["ollama"] = await self._check_ollama_health()
        
        # Check LMStudio
        health["lmstudio"] = await self._check_lmstudio_health()
        
        # Check cloud providers if configured
        if self.config.openai_api_key:
            health["openai"] = await self._check_openai_health()
        
        if self.config.anthropic_api_key:
            health["anthropic"] = await self._check_anthropic_health()
        
        return health
    
    async def _check_ollama_health(self) -> bool:
        """Check Ollama connectivity.
        
        Returns:
            True if Ollama is reachable
        """
        try:
            client = await self._get_http_client()
            response = await client.get(
                f"{self.config.ollama_url}/api/tags",
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception:
            return False
    
    async def _check_lmstudio_health(self) -> bool:
        """Check LMStudio connectivity.
        
        Returns:
            True if LMStudio is reachable
        """
        try:
            client = await self._get_http_client()
            response = await client.get(
                f"{self.config.lmstudio_url}/models",
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception:
            return False
    
    async def _check_openai_health(self) -> bool:
        """Check OpenAI API connectivity.
        
        Returns:
            True if OpenAI API is reachable
        """
        try:
            client = await self._get_http_client()
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {self.config.openai_api_key}"},
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception:
            return False
    
    async def _check_anthropic_health(self) -> bool:
        """Check Anthropic API connectivity.
        
        Returns:
            True if Anthropic API is reachable
        """
        # Anthropic doesn't have a simple health check endpoint
        # We just verify the API key is set
        return bool(self.config.anthropic_api_key)
