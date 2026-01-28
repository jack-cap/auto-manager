"""Unit tests for ManagerIOClient base class.

Tests cover:
- HTTP client initialization and configuration
- X-API-KEY authentication header
- Pagination helper (fetch_all_paginated)
- Redis caching with TTL
- Error handling and retry logic
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.manager_io import (
    ManagerIOClient,
    ManagerIOAuthenticationError,
    ManagerIOConnectionError,
    ManagerIOForbiddenError,
    ManagerIONotFoundError,
    ManagerIORateLimitError,
    ManagerIOServerError,
    ManagerIOValidationError,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    redis.scan_iter = MagicMock(return_value=iter([]))
    return redis


@pytest.fixture
def client(mock_redis):
    """Create a ManagerIOClient with mock Redis."""
    return ManagerIOClient(
        base_url="https://manager.example.com/api2",
        api_key="test-api-key",
        cache=mock_redis,
        cache_ttl=300,
    )


@pytest.fixture
def client_no_cache():
    """Create a ManagerIOClient without caching."""
    return ManagerIOClient(
        base_url="https://manager.example.com/api2",
        api_key="test-api-key",
        cache=None,
    )


# =============================================================================
# Initialization Tests
# =============================================================================


class TestClientInitialization:
    """Tests for ManagerIOClient initialization."""
    
    def test_init_with_all_params(self, mock_redis):
        """Test client initialization with all parameters."""
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2/",
            api_key="my-api-key",
            cache=mock_redis,
            cache_ttl=600,
            page_size=50,
        )
        
        # URL should be normalized (trailing slash removed)
        assert client.base_url == "https://manager.example.com/api2"
        assert client.api_key == "my-api-key"
        assert client.cache == mock_redis
        assert client.cache_ttl == 600
        assert client.page_size == 50
    
    def test_init_with_defaults(self):
        """Test client initialization with default values."""
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="my-api-key",
        )
        
        assert client.cache is None
        assert client.cache_ttl == ManagerIOClient.DEFAULT_CACHE_TTL
        assert client.page_size == ManagerIOClient.DEFAULT_PAGE_SIZE
    
    def test_url_normalization(self):
        """Test that trailing slashes are removed from base URL."""
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2///",
            api_key="my-api-key",
        )
        
        assert client.base_url == "https://manager.example.com/api2"


# =============================================================================
# Authentication Header Tests
# =============================================================================


class TestAuthenticationHeader:
    """Tests for X-API-KEY authentication header."""
    
    @pytest.mark.asyncio
    async def test_api_key_header_in_requests(self, client_no_cache):
        """Test that X-API-KEY header is included in requests."""
        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.is_success = True
            mock_response.json.return_value = {"data": "test"}
            mock_request.return_value = mock_response
            
            # Get the client and check headers
            http_client = await client_no_cache._get_client()
            
            assert http_client.headers["X-API-KEY"] == "test-api-key"
            assert http_client.headers["Content-Type"] == "application/json"
            assert http_client.headers["Accept"] == "application/json"
            
            await client_no_cache.close()


# =============================================================================
# Cache Key Generation Tests
# =============================================================================


class TestCacheKeyGeneration:
    """Tests for cache key generation."""
    
    def test_cache_key_without_params(self, client):
        """Test cache key generation without parameters."""
        key1 = client._get_cache_key("/chart-of-accounts")
        key2 = client._get_cache_key("/chart-of-accounts")
        
        # Same endpoint should produce same key
        assert key1 == key2
        assert key1.startswith("manager_io:")
    
    def test_cache_key_with_params(self, client):
        """Test cache key generation with parameters."""
        key1 = client._get_cache_key("/payments", {"skip": 0, "take": 100})
        key2 = client._get_cache_key("/payments", {"skip": 0, "take": 100})
        key3 = client._get_cache_key("/payments", {"skip": 100, "take": 100})
        
        # Same params should produce same key
        assert key1 == key2
        # Different params should produce different key
        assert key1 != key3
    
    def test_cache_key_param_order_independent(self, client):
        """Test that parameter order doesn't affect cache key."""
        key1 = client._get_cache_key("/payments", {"skip": 0, "take": 100})
        key2 = client._get_cache_key("/payments", {"take": 100, "skip": 0})
        
        # Order shouldn't matter
        assert key1 == key2
    
    def test_different_endpoints_different_keys(self, client):
        """Test that different endpoints produce different keys."""
        key1 = client._get_cache_key("/chart-of-accounts")
        key2 = client._get_cache_key("/suppliers")
        
        assert key1 != key2


# =============================================================================
# Cache Operations Tests
# =============================================================================


class TestCacheOperations:
    """Tests for cache get/set operations."""
    
    @pytest.mark.asyncio
    async def test_get_from_cache_hit(self, client, mock_redis):
        """Test cache hit returns cached data."""
        cached_data = {"key": "123", "name": "Test Account"}
        mock_redis.get.return_value = json.dumps(cached_data)
        
        result = await client._get_from_cache("test-key")
        
        assert result == cached_data
        mock_redis.get.assert_called_once_with("test-key")
    
    @pytest.mark.asyncio
    async def test_get_from_cache_miss(self, client, mock_redis):
        """Test cache miss returns None."""
        mock_redis.get.return_value = None
        
        result = await client._get_from_cache("test-key")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_from_cache_no_redis(self, client_no_cache):
        """Test cache get with no Redis returns None."""
        result = await client_no_cache._get_from_cache("test-key")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_set_cache(self, client, mock_redis):
        """Test setting cache with TTL."""
        data = {"key": "123", "name": "Test"}
        
        await client._set_cache("test-key", data, ttl=600)
        
        mock_redis.setex.assert_called_once_with(
            "test-key",
            600,
            json.dumps(data),
        )
    
    @pytest.mark.asyncio
    async def test_set_cache_default_ttl(self, client, mock_redis):
        """Test setting cache with default TTL."""
        data = {"key": "123"}
        
        await client._set_cache("test-key", data)
        
        mock_redis.setex.assert_called_once_with(
            "test-key",
            300,  # Default TTL
            json.dumps(data),
        )
    
    @pytest.mark.asyncio
    async def test_set_cache_no_redis(self, client_no_cache):
        """Test cache set with no Redis does nothing."""
        # Should not raise
        await client_no_cache._set_cache("test-key", {"data": "test"})


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for HTTP error handling."""
    
    def test_handle_401_error(self, client):
        """Test 401 raises ManagerIOAuthenticationError."""
        response = MagicMock()
        response.is_success = False
        response.status_code = 401
        response.text = "Unauthorized"
        response.json.return_value = {"detail": "Invalid API key"}
        
        with pytest.raises(ManagerIOAuthenticationError) as exc_info:
            client._handle_response_error(response)
        
        assert "Authentication failed" in str(exc_info.value)
    
    def test_handle_403_error(self, client):
        """Test 403 raises ManagerIOForbiddenError."""
        response = MagicMock()
        response.is_success = False
        response.status_code = 403
        response.text = "Forbidden"
        response.json.return_value = {"detail": "Access denied"}
        
        with pytest.raises(ManagerIOForbiddenError) as exc_info:
            client._handle_response_error(response)
        
        assert "Access forbidden" in str(exc_info.value)
    
    def test_handle_404_error(self, client):
        """Test 404 raises ManagerIONotFoundError."""
        response = MagicMock()
        response.is_success = False
        response.status_code = 404
        response.text = "Not Found"
        response.json.return_value = {"detail": "Resource not found"}
        
        with pytest.raises(ManagerIONotFoundError) as exc_info:
            client._handle_response_error(response)
        
        assert "not found" in str(exc_info.value)
    
    def test_handle_422_error(self, client):
        """Test 422 raises ManagerIOValidationError."""
        response = MagicMock()
        response.is_success = False
        response.status_code = 422
        response.text = "Validation Error"
        response.json.return_value = {"detail": "Invalid data"}
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            client._handle_response_error(response)
        
        assert "Validation error" in str(exc_info.value)
    
    def test_handle_429_error(self, client):
        """Test 429 raises ManagerIORateLimitError."""
        response = MagicMock()
        response.is_success = False
        response.status_code = 429
        response.text = "Too Many Requests"
        response.headers = {"Retry-After": "60"}
        response.json.return_value = {"detail": "Rate limited"}
        
        with pytest.raises(ManagerIORateLimitError) as exc_info:
            client._handle_response_error(response)
        
        assert exc_info.value.retry_after == 60
    
    def test_handle_500_error(self, client):
        """Test 5xx raises ManagerIOServerError."""
        response = MagicMock()
        response.is_success = False
        response.status_code = 500
        response.text = "Internal Server Error"
        response.json.return_value = {"detail": "Server error"}
        
        with pytest.raises(ManagerIOServerError) as exc_info:
            client._handle_response_error(response)
        
        assert "Server error" in str(exc_info.value)
    
    def test_handle_success_no_error(self, client):
        """Test successful response doesn't raise."""
        response = MagicMock()
        response.is_success = True
        response.status_code = 200
        
        # Should not raise
        client._handle_response_error(response)


# =============================================================================
# Retry Logic Tests
# =============================================================================


class TestRetryLogic:
    """Tests for exponential backoff retry logic."""
    
    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self, client_no_cache):
        """Test retry on connection errors."""
        call_count = 0
        
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("Connection refused")
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = {"data": "success"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            # Override retry delay for faster tests
            client_no_cache.INITIAL_RETRY_DELAY = 0.01
            client_no_cache.MAX_RETRIES = 3
            
            result = await client_no_cache._get("/test", use_cache=False)
            
            assert result == {"data": "success"}
            assert call_count == 3
        
        await client_no_cache.close()
    
    @pytest.mark.asyncio
    async def test_retry_on_server_error(self, client_no_cache):
        """Test retry on 5xx server errors."""
        call_count = 0
        
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            response = MagicMock()
            if call_count < 2:
                response.is_success = False
                response.status_code = 503
                response.text = "Service Unavailable"
                response.json.return_value = {"detail": "Service unavailable"}
            else:
                response.is_success = True
                response.status_code = 200
                response.json.return_value = {"data": "success"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            client_no_cache.INITIAL_RETRY_DELAY = 0.01
            client_no_cache.MAX_RETRIES = 3
            
            result = await client_no_cache._get("/test", use_cache=False)
            
            assert result == {"data": "success"}
            assert call_count == 2
        
        await client_no_cache.close()
    
    @pytest.mark.asyncio
    async def test_no_retry_on_client_error(self, client_no_cache):
        """Test no retry on 4xx client errors (except 429)."""
        call_count = 0
        
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            response = MagicMock()
            response.is_success = False
            response.status_code = 401
            response.text = "Unauthorized"
            response.json.return_value = {"detail": "Invalid API key"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            client_no_cache.INITIAL_RETRY_DELAY = 0.01
            
            with pytest.raises(ManagerIOAuthenticationError):
                await client_no_cache._get("/test", use_cache=False)
            
            # Should not retry on 401
            assert call_count == 1
        
        await client_no_cache.close()
    
    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, client_no_cache):
        """Test error raised when max retries exceeded."""
        async def mock_request(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            client_no_cache.INITIAL_RETRY_DELAY = 0.01
            client_no_cache.MAX_RETRIES = 2
            
            with pytest.raises(ManagerIOConnectionError):
                await client_no_cache._get("/test", use_cache=False)
        
        await client_no_cache.close()


# =============================================================================
# Pagination Tests
# =============================================================================


class TestPagination:
    """Tests for fetch_all_paginated helper."""
    
    @pytest.mark.asyncio
    async def test_fetch_all_single_page(self, client, mock_redis):
        """Test fetching all records when data fits in one page."""
        records = [{"key": f"id-{i}", "name": f"Item {i}"} for i in range(50)]
        
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = records
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.fetch_all_paginated("/test", use_cache=False)
            
            assert len(result) == 50
            # Records are normalized, so check key fields exist
            for i, r in enumerate(result):
                assert r.get("key") == f"id-{i}"
                assert r.get("name") == f"Item {i}"
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_fetch_all_multiple_pages(self, client, mock_redis):
        """Test fetching all records across multiple pages."""
        all_records = [{"key": f"id-{i}", "name": f"Item {i}"} for i in range(250)]
        page_size = client.page_size  # 100
        
        call_count = 0
        
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            params = kwargs.get("params", {})
            skip = params.get("skip", 0)
            take = params.get("take", page_size)
            
            page_records = all_records[skip:skip + take]
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = page_records
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.fetch_all_paginated("/test", use_cache=False)
            
            assert len(result) == 250
            # Records are normalized, so check key fields exist
            for i, r in enumerate(result):
                assert r.get("key") == f"id-{i}"
                assert r.get("name") == f"Item {i}"
            # Should make 3 requests: 0-100, 100-200, 200-250
            assert call_count == 3
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_fetch_all_with_total_count(self, client, mock_redis):
        """Test fetching with response containing total count."""
        all_records = [{"key": f"id-{i}"} for i in range(150)]
        page_size = client.page_size
        
        async def mock_request(*args, **kwargs):
            params = kwargs.get("params", {})
            skip = params.get("skip", 0)
            take = params.get("take", page_size)
            
            page_records = all_records[skip:skip + take]
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = {
                "items": page_records,
                "total": 150,
                "skip": skip,
                "take": take,
            }
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.fetch_all_paginated("/test", use_cache=False)
            
            assert len(result) == 150
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_fetch_all_empty_result(self, client, mock_redis):
        """Test fetching when no records exist."""
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = []
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.fetch_all_paginated("/test", use_cache=False)
            
            assert result == []
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_fetch_all_uses_cache(self, client, mock_redis):
        """Test that paginated results are cached."""
        records = [{"key": "id-1"}]
        mock_redis.get.return_value = json.dumps(records)
        
        result = await client.fetch_all_paginated("/test", use_cache=True)
        
        assert result == records
        # Should have checked cache
        mock_redis.get.assert_called()
        
        await client.close()


# =============================================================================
# Context Manager Tests
# =============================================================================


class TestContextManager:
    """Tests for async context manager support."""
    
    @pytest.mark.asyncio
    async def test_context_manager(self, mock_redis):
        """Test client works as async context manager."""
        async with ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="test-key",
            cache=mock_redis,
        ) as client:
            assert client.base_url == "https://manager.example.com/api2"
        
        # Client should be closed after exiting context
        assert client._client is None or client._client.is_closed


# =============================================================================
# Data Fetching Methods Tests (Task 5.3)
# =============================================================================


class TestGetChartOfAccounts:
    """Tests for get_chart_of_accounts method."""
    
    @pytest.mark.asyncio
    async def test_get_chart_of_accounts_list_response(self, client, mock_redis):
        """Test fetching accounts with list response format."""
        accounts_data = [
            {"Key": "acc-1", "Name": "Cash", "Code": "1000"},
            {"Key": "acc-2", "Name": "Accounts Receivable", "Code": "1100"},
            {"Key": "acc-3", "Name": "Office Supplies"},  # No code
        ]
        
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = accounts_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_chart_of_accounts()
            
            assert len(result) == 3
            assert result[0].key == "acc-1"
            assert result[0].name == "Cash"
            assert result[0].code == "1000"
            assert result[2].code is None
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_get_chart_of_accounts_dict_response(self, client, mock_redis):
        """Test fetching accounts with dict response format."""
        accounts_data = {
            "items": [
                {"Key": "acc-1", "Name": "Cash"},
            ]
        }
        
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = accounts_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_chart_of_accounts()
            
            assert len(result) == 1
            assert result[0].key == "acc-1"
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_get_chart_of_accounts_uses_cache(self, client, mock_redis):
        """Test that chart of accounts uses caching."""
        cached_data = [{"Key": "acc-1", "Name": "Cached Account"}]
        mock_redis.get.return_value = json.dumps(cached_data)
        
        result = await client.get_chart_of_accounts()
        
        assert len(result) == 1
        assert result[0].name == "Cached Account"
        mock_redis.get.assert_called()
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_get_chart_of_accounts_lowercase_keys(self, client, mock_redis):
        """Test handling lowercase field names from API."""
        accounts_data = [
            {"key": "acc-1", "name": "Cash", "code": "1000"},
        ]
        
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = accounts_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_chart_of_accounts()
            
            assert len(result) == 1
            assert result[0].key == "acc-1"
            assert result[0].name == "Cash"
        
        await client.close()


class TestGetSuppliers:
    """Tests for get_suppliers method."""
    
    @pytest.mark.asyncio
    async def test_get_suppliers_uses_get(self, client, mock_redis):
        """Test that suppliers endpoint uses GET method."""
        suppliers_data = {
            "suppliers": [
                {"key": "sup-1", "name": "Supplier A"},
                {"key": "sup-2", "name": "Supplier B"},
            ]
        }
        
        async def mock_request(method, url, **kwargs):
            # Verify GET method is used
            assert method == "GET"
            assert "/suppliers" in url
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = suppliers_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_suppliers()
            
            assert len(result) == 2
            assert result[0].key == "sup-1"
            assert result[0].name == "Supplier A"
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_get_suppliers_uses_cache(self, client, mock_redis):
        """Test that suppliers uses caching."""
        cached_data = [{"Key": "sup-1", "Name": "Cached Supplier"}]
        mock_redis.get.return_value = json.dumps(cached_data)
        
        result = await client.get_suppliers()
        
        assert len(result) == 1
        assert result[0].name == "Cached Supplier"
        mock_redis.get.assert_called()
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_get_suppliers_caches_result(self, client, mock_redis):
        """Test that suppliers result is cached after fetch."""
        suppliers_data = [{"Key": "sup-1", "Name": "New Supplier"}]
        
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = suppliers_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_suppliers()
            
            assert len(result) == 1
            # Verify cache was set
            mock_redis.setex.assert_called()
        
        await client.close()


class TestGetCustomers:
    """Tests for get_customers method."""
    
    @pytest.mark.asyncio
    async def test_get_customers_list_response(self, client, mock_redis):
        """Test fetching customers with list response format."""
        customers_data = [
            {"Key": "cust-1", "Name": "Customer A"},
            {"Key": "cust-2", "Name": "Customer B"},
        ]
        
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = customers_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_customers()
            
            assert len(result) == 2
            assert result[0].key == "cust-1"
            assert result[0].name == "Customer A"
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_get_customers_uses_cache(self, client, mock_redis):
        """Test that customers uses caching."""
        cached_data = [{"Key": "cust-1", "Name": "Cached Customer"}]
        mock_redis.get.return_value = json.dumps(cached_data)
        
        result = await client.get_customers()
        
        assert len(result) == 1
        assert result[0].name == "Cached Customer"
        mock_redis.get.assert_called()
        
        await client.close()


class TestPaginatedEndpoints:
    """Tests for paginated data fetching methods."""
    
    @pytest.mark.asyncio
    async def test_get_payments(self, client, mock_redis):
        """Test fetching payments with pagination."""
        payments_data = [
            {"Key": "pay-1", "Amount": 100.00},
            {"Key": "pay-2", "Amount": 200.00},
        ]
        
        async def mock_request(method, url, params=None, **kwargs):
            assert method == "GET"
            assert "/payments" in url
            assert params["skip"] == 0
            assert params["take"] == 50
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = payments_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_payments(skip=0, take=50)
            
            assert len(result.items) == 2
            assert result.skip == 0
            assert result.take == 50
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_get_receipts(self, client, mock_redis):
        """Test fetching receipts with pagination."""
        receipts_data = [{"Key": "rec-1", "Amount": 150.00}]
        
        async def mock_request(method, url, params=None, **kwargs):
            assert method == "GET"
            assert "/receipts" in url
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = receipts_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_receipts(skip=10, take=25)
            
            assert len(result.items) == 1
            assert result.skip == 10
            assert result.take == 25
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_get_transfers(self, client, mock_redis):
        """Test fetching transfers with pagination."""
        transfers_data = [{"Key": "trans-1", "Amount": 500.00}]
        
        async def mock_request(method, url, params=None, **kwargs):
            assert method == "GET"
            assert "/inter-account-transfers" in url
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = transfers_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_transfers()
            
            assert len(result.items) == 1
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_get_journal_entries(self, client, mock_redis):
        """Test fetching journal entries with pagination."""
        journal_data = [
            {"Key": "je-1", "Debit": 100.00, "Credit": 0},
            {"Key": "je-2", "Debit": 0, "Credit": 100.00},
        ]
        
        async def mock_request(method, url, params=None, **kwargs):
            assert method == "GET"
            assert "/journal-entry-lines" in url
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = journal_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_journal_entries()
            
            assert len(result.items) == 2
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_paginated_response_with_total(self, client, mock_redis):
        """Test paginated response with total count in response."""
        response_data = {
            "items": [{"Key": "item-1"}],
            "total": 100,
        }
        
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = response_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_payments()
            
            assert result.total == 100
            assert len(result.items) == 1
        
        await client.close()


class TestGetGeneralLedger:
    """Tests for get_general_ledger method."""
    
    @pytest.mark.asyncio
    async def test_get_general_ledger(self, client, mock_redis):
        """Test fetching general ledger view."""
        ledger_data = {
            "transactions": [
                {"Date": "2024-01-01", "Description": "Opening Balance", "Amount": 1000.00},
            ],
            "balance": 1000.00,
        }
        
        async def mock_request(method, url, **kwargs):
            assert method == "GET"
            assert "/general-ledger-transactions-view/view-123" in url
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = ledger_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_general_ledger("view-123")
            
            assert result["balance"] == 1000.00
            assert len(result["transactions"]) == 1
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_get_general_ledger_not_found(self, client, mock_redis):
        """Test general ledger with invalid view ID."""
        from app.services.manager_io import ManagerIONotFoundError
        
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = False
            response.status_code = 404
            response.text = "Not Found"
            response.json.return_value = {"detail": "View not found"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            with pytest.raises(ManagerIONotFoundError):
                await client.get_general_ledger("invalid-view")
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_get_general_ledger_no_cache(self, client, mock_redis):
        """Test that general ledger does not use cache."""
        ledger_data = {"transactions": [], "balance": 0}
        
        request_count = 0
        
        async def mock_request(*args, **kwargs):
            nonlocal request_count
            request_count += 1
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = ledger_data
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            # Call twice
            await client.get_general_ledger("view-1")
            await client.get_general_ledger("view-1")
            
            # Should make 2 requests (no caching)
            assert request_count == 2
        
        await client.close()


# =============================================================================
# Entry Submission Methods Tests (Task 5.4)
# =============================================================================


class TestCreateExpenseClaim:
    """Tests for create_expense_claim method."""
    
    @pytest.mark.asyncio
    async def test_create_expense_claim_success(self, client, mock_redis):
        """Test successful expense claim creation."""
        from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine
        
        expense_data = ExpenseClaimData(
            date="2024-01-15",
            paid_by="employee-uuid-123",
            payee="Restaurant ABC",
            description="Team lunch",
            lines=[
                ExpenseClaimLine(
                    account="expense-account-uuid",
                    line_description="Lunch for 4 people",
                    qty=1,
                    purchase_unit_price=150.00,
                )
            ],
        )
        
        async def mock_request(method, url, json=None, **kwargs):
            assert method == "POST"
            assert "/expense-claim-form" in url
            
            # Verify payload structure
            assert json["Date"] == "2024-01-15"
            assert json["PaidBy"] == "employee-uuid-123"
            assert json["Payee"] == "Restaurant ABC"
            assert json["Description"] == "Team lunch"
            assert json["HasLineDescription"] is True
            assert len(json["Lines"]) == 1
            assert json["Lines"][0]["Account"] == "expense-account-uuid"
            assert json["Lines"][0]["LineDescription"] == "Lunch for 4 people"
            assert json["Lines"][0]["Qty"] == 1
            assert json["Lines"][0]["PurchaseUnitPrice"] == 150.00
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = {"Key": "new-expense-claim-uuid"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.create_expense_claim(expense_data)
            
            assert result.success is True
            assert result.key == "new-expense-claim-uuid"
            assert "successfully" in result.message.lower()
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_expense_claim_multiple_lines(self, client, mock_redis):
        """Test expense claim with multiple line items."""
        from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine
        
        expense_data = ExpenseClaimData(
            date="2024-01-15",
            paid_by="employee-uuid",
            payee="Office Store",
            description="Office supplies",
            lines=[
                ExpenseClaimLine(
                    account="supplies-account",
                    line_description="Printer paper",
                    qty=5,
                    purchase_unit_price=10.00,
                ),
                ExpenseClaimLine(
                    account="supplies-account",
                    line_description="Ink cartridges",
                    qty=2,
                    purchase_unit_price=45.00,
                ),
            ],
        )
        
        async def mock_request(method, url, json=None, **kwargs):
            assert len(json["Lines"]) == 2
            assert json["Lines"][0]["Qty"] == 5
            assert json["Lines"][1]["Qty"] == 2
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = {"Key": "expense-uuid"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.create_expense_claim(expense_data)
            
            assert result.success is True
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_expense_claim_validation_missing_date(self, client, mock_redis):
        """Test validation error for missing date."""
        from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine, ManagerIOValidationError
        
        expense_data = ExpenseClaimData(
            date="",  # Missing date
            paid_by="employee-uuid",
            payee="Restaurant",
            description="Lunch",
            lines=[
                ExpenseClaimLine(
                    account="account-uuid",
                    line_description="Food",
                    qty=1,
                    purchase_unit_price=50.00,
                )
            ],
        )
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            await client.create_expense_claim(expense_data)
        
        assert "Date is required" in str(exc_info.value)
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_expense_claim_validation_missing_paid_by(self, client, mock_redis):
        """Test validation error for missing paid_by."""
        from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine, ManagerIOValidationError
        
        expense_data = ExpenseClaimData(
            date="2024-01-15",
            paid_by="",  # Missing paid_by
            payee="Restaurant",
            description="Lunch",
            lines=[
                ExpenseClaimLine(
                    account="account-uuid",
                    line_description="Food",
                    qty=1,
                    purchase_unit_price=50.00,
                )
            ],
        )
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            await client.create_expense_claim(expense_data)
        
        assert "PaidBy" in str(exc_info.value)
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_expense_claim_validation_empty_lines(self, client, mock_redis):
        """Test validation error for empty lines."""
        from app.services.manager_io import ExpenseClaimData, ManagerIOValidationError
        
        expense_data = ExpenseClaimData(
            date="2024-01-15",
            paid_by="employee-uuid",
            payee="Restaurant",
            description="Lunch",
            lines=[],  # Empty lines
        )
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            await client.create_expense_claim(expense_data)
        
        assert "At least one line item is required" in str(exc_info.value)
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_expense_claim_validation_invalid_qty(self, client, mock_redis):
        """Test validation error for invalid quantity."""
        from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine, ManagerIOValidationError
        
        expense_data = ExpenseClaimData(
            date="2024-01-15",
            paid_by="employee-uuid",
            payee="Restaurant",
            description="Lunch",
            lines=[
                ExpenseClaimLine(
                    account="account-uuid",
                    line_description="Food",
                    qty=0,  # Invalid qty
                    purchase_unit_price=50.00,
                )
            ],
        )
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            await client.create_expense_claim(expense_data)
        
        assert "Quantity must be positive" in str(exc_info.value)
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_expense_claim_api_error(self, client, mock_redis):
        """Test handling of API errors."""
        from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine
        
        expense_data = ExpenseClaimData(
            date="2024-01-15",
            paid_by="employee-uuid",
            payee="Restaurant",
            description="Lunch",
            lines=[
                ExpenseClaimLine(
                    account="account-uuid",
                    line_description="Food",
                    qty=1,
                    purchase_unit_price=50.00,
                )
            ],
        )
        
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = False
            response.status_code = 500
            response.text = "Internal Server Error"
            response.json.return_value = {"detail": "Server error"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.create_expense_claim(expense_data)
            
            assert result.success is False
            assert result.key is None
            assert "Server error" in result.message
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_expense_claim_payload_structure(self, client, mock_redis):
        """Test that payload includes all required Manager.io fields."""
        from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine
        
        expense_data = ExpenseClaimData(
            date="2024-01-15",
            paid_by="employee-uuid",
            payee="Restaurant",
            description="Lunch",
            lines=[
                ExpenseClaimLine(
                    account="account-uuid",
                    line_description="Food",
                    qty=1,
                    purchase_unit_price=50.00,
                )
            ],
        )
        
        captured_payload = None
        
        async def mock_request(method, url, json=None, **kwargs):
            nonlocal captured_payload
            captured_payload = json
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = {"Key": "uuid"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            await client.create_expense_claim(expense_data)
            
            # Verify all required fields are present
            assert "Date" in captured_payload
            assert "PaidBy" in captured_payload
            assert "Payee" in captured_payload
            assert "Description" in captured_payload
            assert "Lines" in captured_payload
            assert "HasLineDescription" in captured_payload
            assert "ExpenseClaimFooters" in captured_payload
            assert "CustomFields" in captured_payload
            assert "CustomFields2" in captured_payload
            
            # Verify line structure
            line = captured_payload["Lines"][0]
            assert "Account" in line
            assert "LineDescription" in line
            assert "Qty" in line
            assert "PurchaseUnitPrice" in line
            assert "CustomFields" in line
            assert "CustomFields2" in line
        
        await client.close()


class TestCreatePurchaseInvoice:
    """Tests for create_purchase_invoice method."""
    
    @pytest.mark.asyncio
    async def test_create_purchase_invoice_success(self, client, mock_redis):
        """Test successful purchase invoice creation."""
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine
        
        invoice_data = PurchaseInvoiceData(
            issue_date="2024-01-15",
            reference="#INV-001",
            description="Office supplies",
            supplier="supplier-uuid-123",
            lines=[
                PurchaseInvoiceLine(
                    account="expense-account-uuid",
                    line_description="Printer paper and ink",
                    purchase_unit_price=89.99,
                )
            ],
        )
        
        async def mock_request(method, url, json=None, **kwargs):
            assert method == "POST"
            assert "/purchase-invoice-form" in url
            
            # Verify payload structure
            assert json["IssueDate"] == "2024-01-15"
            assert json["Reference"] == "#INV-001"
            assert json["Description"] == "Office supplies"
            assert json["Supplier"] == "supplier-uuid-123"
            assert json["HasLineNumber"] is True
            assert json["HasLineDescription"] is True
            assert len(json["Lines"]) == 1
            assert json["Lines"][0]["Account"] == "expense-account-uuid"
            assert json["Lines"][0]["LineDescription"] == "Printer paper and ink"
            assert json["Lines"][0]["PurchaseUnitPrice"] == 89.99
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = {"Key": "new-invoice-uuid"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.create_purchase_invoice(invoice_data)
            
            assert result.success is True
            assert result.key == "new-invoice-uuid"
            assert "successfully" in result.message.lower()
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_purchase_invoice_multiple_lines(self, client, mock_redis):
        """Test purchase invoice with multiple line items."""
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine
        
        invoice_data = PurchaseInvoiceData(
            issue_date="2024-01-15",
            reference="#INV-002",
            description="Equipment purchase",
            supplier="supplier-uuid",
            lines=[
                PurchaseInvoiceLine(
                    account="equipment-account",
                    line_description="Laptop",
                    purchase_unit_price=1200.00,
                ),
                PurchaseInvoiceLine(
                    account="equipment-account",
                    line_description="Monitor",
                    purchase_unit_price=350.00,
                ),
                PurchaseInvoiceLine(
                    account="supplies-account",
                    line_description="Keyboard and mouse",
                    purchase_unit_price=75.00,
                ),
            ],
        )
        
        async def mock_request(method, url, json=None, **kwargs):
            assert len(json["Lines"]) == 3
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = {"Key": "invoice-uuid"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.create_purchase_invoice(invoice_data)
            
            assert result.success is True
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_purchase_invoice_validation_missing_issue_date(self, client, mock_redis):
        """Test validation error for missing issue date."""
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine, ManagerIOValidationError
        
        invoice_data = PurchaseInvoiceData(
            issue_date="",  # Missing issue_date
            reference="#INV-001",
            description="Supplies",
            supplier="supplier-uuid",
            lines=[
                PurchaseInvoiceLine(
                    account="account-uuid",
                    line_description="Item",
                    purchase_unit_price=50.00,
                )
            ],
        )
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            await client.create_purchase_invoice(invoice_data)
        
        assert "IssueDate is required" in str(exc_info.value)
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_purchase_invoice_validation_missing_supplier(self, client, mock_redis):
        """Test validation error for missing supplier."""
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine, ManagerIOValidationError
        
        invoice_data = PurchaseInvoiceData(
            issue_date="2024-01-15",
            reference="#INV-001",
            description="Supplies",
            supplier="",  # Missing supplier
            lines=[
                PurchaseInvoiceLine(
                    account="account-uuid",
                    line_description="Item",
                    purchase_unit_price=50.00,
                )
            ],
        )
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            await client.create_purchase_invoice(invoice_data)
        
        assert "Supplier is required" in str(exc_info.value)
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_purchase_invoice_validation_empty_lines(self, client, mock_redis):
        """Test validation error for empty lines."""
        from app.services.manager_io import PurchaseInvoiceData, ManagerIOValidationError
        
        invoice_data = PurchaseInvoiceData(
            issue_date="2024-01-15",
            reference="#INV-001",
            description="Supplies",
            supplier="supplier-uuid",
            lines=[],  # Empty lines
        )
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            await client.create_purchase_invoice(invoice_data)
        
        assert "At least one line item is required" in str(exc_info.value)
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_purchase_invoice_validation_negative_price(self, client, mock_redis):
        """Test validation error for negative unit price."""
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine, ManagerIOValidationError
        
        invoice_data = PurchaseInvoiceData(
            issue_date="2024-01-15",
            reference="#INV-001",
            description="Supplies",
            supplier="supplier-uuid",
            lines=[
                PurchaseInvoiceLine(
                    account="account-uuid",
                    line_description="Item",
                    purchase_unit_price=-50.00,  # Negative price
                )
            ],
        )
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            await client.create_purchase_invoice(invoice_data)
        
        assert "Unit price cannot be negative" in str(exc_info.value)
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_purchase_invoice_api_error(self, client, mock_redis):
        """Test handling of API errors."""
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine
        
        invoice_data = PurchaseInvoiceData(
            issue_date="2024-01-15",
            reference="#INV-001",
            description="Supplies",
            supplier="supplier-uuid",
            lines=[
                PurchaseInvoiceLine(
                    account="account-uuid",
                    line_description="Item",
                    purchase_unit_price=50.00,
                )
            ],
        )
        
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = False
            response.status_code = 500
            response.text = "Internal Server Error"
            response.json.return_value = {"detail": "Server error"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.create_purchase_invoice(invoice_data)
            
            assert result.success is False
            assert result.key is None
            assert "Server error" in result.message
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_purchase_invoice_payload_structure(self, client, mock_redis):
        """Test that payload includes all required Manager.io fields."""
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine
        
        invoice_data = PurchaseInvoiceData(
            issue_date="2024-01-15",
            reference="#INV-001",
            description="Supplies",
            supplier="supplier-uuid",
            lines=[
                PurchaseInvoiceLine(
                    account="account-uuid",
                    line_description="Item",
                    purchase_unit_price=50.00,
                )
            ],
        )
        
        captured_payload = None
        
        async def mock_request(method, url, json=None, **kwargs):
            nonlocal captured_payload
            captured_payload = json
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = {"Key": "uuid"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            await client.create_purchase_invoice(invoice_data)
            
            # Verify all required fields are present
            assert "IssueDate" in captured_payload
            assert "Reference" in captured_payload
            assert "Description" in captured_payload
            assert "Supplier" in captured_payload
            assert "Lines" in captured_payload
            assert "HasLineNumber" in captured_payload
            assert "HasLineDescription" in captured_payload
            
            # Verify line structure
            line = captured_payload["Lines"][0]
            assert "Account" in line
            assert "LineDescription" in line
            assert "PurchaseUnitPrice" in line
            assert "CustomFields" in line
            assert "CustomFields2" in line
        
        await client.close()


class TestUpdateEntry:
    """Tests for update_entry method."""
    
    @pytest.mark.asyncio
    async def test_update_entry_success(self, client, mock_redis):
        """Test successful entry update."""
        async def mock_request(method, url, json=None, **kwargs):
            assert method == "PUT"
            assert "/expense-claim-form/entry-uuid-123" in url
            assert json["Description"] == "Updated description"
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = {}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.update_entry(
                entry_type="expense-claim-form",
                entry_id="entry-uuid-123",
                data={"Description": "Updated description"},
            )
            
            assert result.success is True
            assert "successfully" in result.message.lower()
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_update_entry_purchase_invoice(self, client, mock_redis):
        """Test updating a purchase invoice."""
        async def mock_request(method, url, json=None, **kwargs):
            assert method == "PUT"
            assert "/purchase-invoice-form/invoice-uuid" in url
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = {}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.update_entry(
                entry_type="purchase-invoice-form",
                entry_id="invoice-uuid",
                data={"Reference": "#INV-002-UPDATED"},
            )
            
            assert result.success is True
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_update_entry_validation_missing_type(self, client, mock_redis):
        """Test validation error for missing entry type."""
        from app.services.manager_io import ManagerIOValidationError
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            await client.update_entry(
                entry_type="",  # Missing type
                entry_id="entry-uuid",
                data={"Description": "Updated"},
            )
        
        assert "Entry type is required" in str(exc_info.value)
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_update_entry_validation_missing_id(self, client, mock_redis):
        """Test validation error for missing entry ID."""
        from app.services.manager_io import ManagerIOValidationError
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            await client.update_entry(
                entry_type="expense-claim-form",
                entry_id="",  # Missing ID
                data={"Description": "Updated"},
            )
        
        assert "Entry ID is required" in str(exc_info.value)
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_update_entry_validation_missing_data(self, client, mock_redis):
        """Test validation error for missing update data."""
        from app.services.manager_io import ManagerIOValidationError
        
        with pytest.raises(ManagerIOValidationError) as exc_info:
            await client.update_entry(
                entry_type="expense-claim-form",
                entry_id="entry-uuid",
                data={},  # Empty data
            )
        
        assert "Update data is required" in str(exc_info.value)
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_update_entry_not_found(self, client, mock_redis):
        """Test handling of not found error."""
        from app.services.manager_io import ManagerIONotFoundError
        
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = False
            response.status_code = 404
            response.text = "Not Found"
            response.json.return_value = {"detail": "Entry not found"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            with pytest.raises(ManagerIONotFoundError):
                await client.update_entry(
                    entry_type="expense-claim-form",
                    entry_id="nonexistent-uuid",
                    data={"Description": "Updated"},
                )
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_update_entry_api_error(self, client, mock_redis):
        """Test handling of API errors."""
        async def mock_request(*args, **kwargs):
            response = MagicMock()
            response.is_success = False
            response.status_code = 500
            response.text = "Internal Server Error"
            response.json.return_value = {"detail": "Server error"}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.update_entry(
                entry_type="expense-claim-form",
                entry_id="entry-uuid",
                data={"Description": "Updated"},
            )
            
            assert result.success is False
            assert "Server error" in result.message
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_update_entry_strips_leading_slash(self, client, mock_redis):
        """Test that leading slashes in entry_type are handled."""
        async def mock_request(method, url, **kwargs):
            # Should not have double slashes
            assert "//expense-claim-form" not in url
            assert "/expense-claim-form/entry-uuid" in url
            
            response = MagicMock()
            response.is_success = True
            response.status_code = 200
            response.json.return_value = {}
            return response
        
        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.update_entry(
                entry_type="/expense-claim-form",  # Leading slash
                entry_id="entry-uuid",
                data={"Description": "Updated"},
            )
            
            assert result.success is True
        
        await client.close()
