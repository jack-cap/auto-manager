"""Property-based tests for LLM service functionality.

Uses Hypothesis for property-based testing to validate universal correctness
properties across all valid inputs.

Feature: manager-io-bookkeeper

Properties tested:
- Property 17: LLM Routing by Configuration
- Property 18: Model Fallback

**Validates: Requirements 8.2, 8.3, 8.5**
"""

import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hyp_settings, strategies as st, assume

from app.services.llm import (
    LLMConfig,
    LLMConnectionError,
    LLMError,
    LLMModelNotFoundError,
    LLMService,
    Message,
)


# =============================================================================
# Custom Strategies
# =============================================================================

# Provider strategy
provider_strategy = st.sampled_from(["ollama", "lmstudio", "openai", "anthropic"])

# Model name strategy (without provider prefix)
model_name_strategy = st.sampled_from([
    "llama3", "mistral", "codellama", "gpt-4", "gpt-3.5-turbo",
    "claude-3-opus", "claude-3-sonnet", "gemma", "phi-3",
])

# Model with provider prefix strategy
model_with_prefix_strategy = st.sampled_from([
    "ollama/llama3", "ollama/mistral", "ollama/codellama",
    "openai/gpt-4", "openai/gpt-3.5-turbo",
    "anthropic/claude-3-opus", "anthropic/claude-3-sonnet",
])

# Temperature strategy
temperature_strategy = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

# Message content strategy
message_content_strategy = st.text(min_size=1, max_size=200).filter(lambda x: len(x.strip()) > 0)


# =============================================================================
# Helper Functions
# =============================================================================

def create_mock_litellm_response(content: str):
    """Create a mock LiteLLM response."""
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=content))
    ]
    return mock_response


# =============================================================================
# Property 17: LLM Routing by Configuration
# =============================================================================


class TestLLMRoutingByConfigurationProperty:
    """Property 17: LLM Routing by Configuration
    
    For any LLM request with a specific provider configuration (local/cloud),
    the request SHALL be routed to the configured provider endpoint.
    
    **Validates: Requirements 8.2, 8.3**
    """
    
    @given(
        provider=provider_strategy,
        model_name=model_name_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_model_resolution_adds_provider_prefix(
        self,
        provider: str,
        model_name: str,
    ):
        """Feature: manager-io-bookkeeper, Property 17: LLM Routing by Configuration
        
        Model resolution SHALL add the configured provider prefix.
        **Validates: Requirements 8.2, 8.3**
        """
        config = LLMConfig(
            default_provider=provider,
            default_model=model_name,
        )
        
        llm = LLMService(config)
        
        # Resolve model without explicit prefix
        resolved = llm._resolve_model(model_name)
        
        # Property: resolved model has provider prefix
        assert "/" in resolved, \
            f"Resolved model should have provider prefix: {resolved}"
        
        # Property: prefix matches configured provider (or openai for lmstudio)
        prefix = resolved.split("/")[0]
        if provider == "lmstudio":
            # LMStudio uses OpenAI-compatible API
            assert prefix == "openai", \
                f"LMStudio should use openai prefix, got {prefix}"
        else:
            assert prefix == provider, \
                f"Prefix should be {provider}, got {prefix}"
    
    @given(
        model_with_prefix=model_with_prefix_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_model_with_prefix_unchanged(
        self,
        model_with_prefix: str,
    ):
        """Feature: manager-io-bookkeeper, Property 17: LLM Routing by Configuration
        
        Models with explicit provider prefix SHALL remain unchanged.
        **Validates: Requirements 8.2, 8.3**
        """
        config = LLMConfig(
            default_provider="ollama",
            default_model="llama3",
        )
        
        llm = LLMService(config)
        
        # Resolve model with explicit prefix
        resolved = llm._resolve_model(model_with_prefix)
        
        # Property: model with prefix is unchanged
        assert resolved == model_with_prefix, \
            f"Model with prefix should be unchanged: {model_with_prefix} -> {resolved}"
    
    @given(
        provider=st.sampled_from(["ollama", "lmstudio"]),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_local_provider_uses_local_api_base(
        self,
        provider: str,
    ):
        """Feature: manager-io-bookkeeper, Property 17: LLM Routing by Configuration
        
        Local providers (Ollama/LMStudio) SHALL use local API base URLs.
        **Validates: Requirements 8.2**
        """
        ollama_url = "http://localhost:11434"
        lmstudio_url = "http://localhost:1234/v1"
        
        config = LLMConfig(
            default_provider=provider,
            default_model="llama3",
            ollama_url=ollama_url,
            lmstudio_url=lmstudio_url,
        )
        
        llm = LLMService(config)
        
        # Resolve model and get API base
        resolved = llm._resolve_model("llama3")
        api_base = llm._get_api_base(resolved)
        
        # Property: local provider uses local URL
        if provider == "ollama":
            assert api_base == ollama_url, \
                f"Ollama should use {ollama_url}, got {api_base}"
        elif provider == "lmstudio":
            assert api_base == lmstudio_url, \
                f"LMStudio should use {lmstudio_url}, got {api_base}"
    
    @given(
        provider=st.sampled_from(["openai", "anthropic"]),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_cloud_provider_uses_default_api_base(
        self,
        provider: str,
    ):
        """Feature: manager-io-bookkeeper, Property 17: LLM Routing by Configuration
        
        Cloud providers (OpenAI/Anthropic) SHALL use default API base (None).
        **Validates: Requirements 8.3**
        """
        config = LLMConfig(
            default_provider=provider,
            default_model="gpt-4" if provider == "openai" else "claude-3-opus",
        )
        
        llm = LLMService(config)
        
        # Get API base for cloud provider model
        model = f"{provider}/test-model"
        api_base = llm._get_api_base(model)
        
        # Property: cloud provider uses None (default LiteLLM URLs)
        assert api_base is None, \
            f"Cloud provider {provider} should use None api_base, got {api_base}"
    
    @given(
        response_text=message_content_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_chat_routes_to_configured_provider(
        self,
        response_text: str,
    ):
        """Feature: manager-io-bookkeeper, Property 17: LLM Routing by Configuration
        
        Chat requests SHALL be routed to the configured provider.
        **Validates: Requirements 8.2, 8.3**
        """
        async def run_test():
            config = LLMConfig(
                default_provider="ollama",
                default_model="llama3",
                ollama_url="http://localhost:11434",
            )
            
            llm = LLMService(config)
            
            # Track the model used in the call
            called_model = None
            called_api_base = None
            
            async def mock_acompletion(**kwargs):
                nonlocal called_model, called_api_base
                called_model = kwargs.get("model")
                called_api_base = kwargs.get("api_base")
                return create_mock_litellm_response(response_text)
            
            try:
                with patch("app.services.llm.litellm.acompletion", side_effect=mock_acompletion):
                    messages = [Message(role="user", content="Hello")]
                    result = await llm.chat(messages)
                    
                    # Property: model was routed correctly
                    assert called_model == "ollama/llama3", \
                        f"Expected ollama/llama3, got {called_model}"
                    
                    # Property: API base was set correctly
                    assert called_api_base == "http://localhost:11434", \
                        f"Expected ollama URL, got {called_api_base}"
                    
                    # Property: response was returned
                    assert result == response_text, \
                        f"Expected {response_text}, got {result}"
            finally:
                await llm.close()
        
        asyncio.run(run_test())


# =============================================================================
# Property 18: Model Fallback
# =============================================================================


class TestModelFallbackProperty:
    """Property 18: Model Fallback
    
    For any LLM request where the primary model is unavailable, the system
    SHALL attempt the configured fallback model before returning an error.
    
    **Validates: Requirements 8.5**
    """
    
    @given(
        fallback_response=message_content_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_fallback_used_when_primary_unavailable(
        self,
        fallback_response: str,
    ):
        """Feature: manager-io-bookkeeper, Property 18: Model Fallback
        
        When primary model is unavailable, fallback model SHALL be tried.
        **Validates: Requirements 8.5**
        """
        async def run_test():
            config = LLMConfig(
                default_provider="ollama",
                default_model="primary-model",
                fallback_models=["ollama/fallback-model"],
            )
            
            llm = LLMService(config)
            
            # Track which models were tried
            models_tried = []
            
            async def mock_call_litellm(model, messages, temperature=0.7, max_tokens=None, api_base=None):
                models_tried.append(model)
                
                if model == "ollama/primary-model":
                    # Primary model fails with connection error
                    raise LLMConnectionError("Primary model unavailable")
                else:
                    # Fallback succeeds
                    return fallback_response
            
            try:
                with patch.object(llm, "_call_litellm", side_effect=mock_call_litellm):
                    messages = [Message(role="user", content="Hello")]
                    result = await llm.chat(messages)
                    
                    # Property: primary model was tried first
                    assert "ollama/primary-model" in models_tried, \
                        "Primary model should be tried first"
                    
                    # Property: fallback model was tried after primary failed
                    assert "ollama/fallback-model" in models_tried, \
                        "Fallback model should be tried after primary fails"
                    
                    # Property: primary was tried before fallback
                    primary_idx = models_tried.index("ollama/primary-model")
                    fallback_idx = models_tried.index("ollama/fallback-model")
                    assert primary_idx < fallback_idx, \
                        "Primary should be tried before fallback"
                    
                    # Property: fallback response was returned
                    assert result == fallback_response, \
                        f"Expected fallback response, got {result}"
            finally:
                await llm.close()
        
        asyncio.run(run_test())
    
    @given(
        num_fallbacks=st.integers(min_value=1, max_value=3),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_multiple_fallbacks_tried_in_order(
        self,
        num_fallbacks: int,
    ):
        """Feature: manager-io-bookkeeper, Property 18: Model Fallback
        
        Multiple fallback models SHALL be tried in priority order.
        **Validates: Requirements 8.5**
        """
        async def run_test():
            fallback_models = [f"ollama/fallback-{i}" for i in range(num_fallbacks)]
            
            config = LLMConfig(
                default_provider="ollama",
                default_model="primary-model",
                fallback_models=fallback_models,
            )
            
            llm = LLMService(config)
            
            # Track which models were tried
            models_tried = []
            
            async def mock_call_litellm(model, messages, temperature=0.7, max_tokens=None, api_base=None):
                models_tried.append(model)
                
                # All models fail except the last fallback
                if model == fallback_models[-1]:
                    return "Success from last fallback"
                else:
                    raise LLMConnectionError(f"Model {model} unavailable")
            
            try:
                with patch.object(llm, "_call_litellm", side_effect=mock_call_litellm):
                    messages = [Message(role="user", content="Hello")]
                    result = await llm.chat(messages)
                    
                    # Property: all models were tried in order
                    expected_order = ["ollama/primary-model"] + fallback_models
                    assert models_tried == expected_order, \
                        f"Expected order {expected_order}, got {models_tried}"
                    
                    # Property: last fallback response was returned
                    assert result == "Success from last fallback", \
                        f"Expected success from last fallback, got {result}"
            finally:
                await llm.close()
        
        asyncio.run(run_test())
    
    def test_error_raised_when_all_models_fail(self):
        """Feature: manager-io-bookkeeper, Property 18: Model Fallback
        
        When all models fail, an error SHALL be raised.
        **Validates: Requirements 8.5**
        """
        async def run_test():
            config = LLMConfig(
                default_provider="ollama",
                default_model="primary-model",
                fallback_models=["ollama/fallback-1", "ollama/fallback-2"],
            )
            
            llm = LLMService(config)
            
            async def mock_call_litellm(model, messages, temperature=0.7, max_tokens=None, api_base=None):
                # All models fail
                raise LLMConnectionError("Model unavailable")
            
            try:
                with patch.object(llm, "_call_litellm", side_effect=mock_call_litellm):
                    messages = [Message(role="user", content="Hello")]
                    
                    # Property: error is raised when all models fail
                    with pytest.raises(LLMConnectionError):
                        await llm.chat(messages)
            finally:
                await llm.close()
        
        asyncio.run(run_test())
    
    @given(
        response_text=message_content_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_no_fallback_when_primary_succeeds(
        self,
        response_text: str,
    ):
        """Feature: manager-io-bookkeeper, Property 18: Model Fallback
        
        When primary model succeeds, fallback models SHALL NOT be tried.
        **Validates: Requirements 8.5**
        """
        async def run_test():
            config = LLMConfig(
                default_provider="ollama",
                default_model="primary-model",
                fallback_models=["ollama/fallback-1", "ollama/fallback-2"],
            )
            
            llm = LLMService(config)
            
            # Track which models were tried
            models_tried = []
            
            async def mock_call_litellm(model, messages, temperature=0.7, max_tokens=None, api_base=None):
                models_tried.append(model)
                # Primary succeeds
                return response_text
            
            try:
                with patch.object(llm, "_call_litellm", side_effect=mock_call_litellm):
                    messages = [Message(role="user", content="Hello")]
                    result = await llm.chat(messages)
                    
                    # Property: only primary model was tried
                    assert models_tried == ["ollama/primary-model"], \
                        f"Only primary should be tried when it succeeds, got {models_tried}"
                    
                    # Property: primary response was returned
                    assert result == response_text, \
                        f"Expected primary response, got {result}"
            finally:
                await llm.close()
        
        asyncio.run(run_test())
    
    @given(
        response_text=message_content_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_fallback_on_model_not_found_error(
        self,
        response_text: str,
    ):
        """Feature: manager-io-bookkeeper, Property 18: Model Fallback
        
        Fallback SHALL be triggered on LLMModelNotFoundError.
        **Validates: Requirements 8.5**
        """
        async def run_test():
            config = LLMConfig(
                default_provider="ollama",
                default_model="nonexistent-model",
                fallback_models=["ollama/fallback-model"],
            )
            
            llm = LLMService(config)
            
            # Track which models were tried
            models_tried = []
            
            async def mock_call_litellm(model, messages, temperature=0.7, max_tokens=None, api_base=None):
                models_tried.append(model)
                
                if model == "ollama/nonexistent-model":
                    raise LLMModelNotFoundError("Model not found")
                else:
                    return response_text
            
            try:
                with patch.object(llm, "_call_litellm", side_effect=mock_call_litellm):
                    messages = [Message(role="user", content="Hello")]
                    result = await llm.chat(messages)
                    
                    # Property: fallback was tried after model not found
                    assert "ollama/fallback-model" in models_tried, \
                        "Fallback should be tried after model not found"
                    
                    # Property: fallback response was returned
                    assert result == response_text, \
                        f"Expected fallback response, got {result}"
            finally:
                await llm.close()
        
        asyncio.run(run_test())
