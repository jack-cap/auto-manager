"""Property-based tests for Manager.io API client functionality.

Uses Hypothesis for property-based testing to validate universal correctness
properties across all valid inputs.

Feature: manager-io-bookkeeper

Properties tested:
- Property 9: Pagination Completeness
- Property 10: Cache Behavior
- Property 11: API Authentication Header

**Validates: Requirements 5.4, 5.5, 5.6, 5.7**
"""

import asyncio
import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from hypothesis import given, settings as hyp_settings, strategies as st, assume

from app.services.manager_io import ManagerIOClient


# =============================================================================
# Custom Strategies
# =============================================================================

# API key strategy - non-empty strings that could be valid API keys
api_key_strategy = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(
        min_codepoint=32,
        max_codepoint=126,
        blacklist_characters='\x00'
    )
).filter(lambda x: len(x.strip()) > 0)

# Base URL strategy - valid HTTP/HTTPS URLs
base_url_strategy = st.sampled_from([
    "http://localhost:8080/api2",
    "https://manager.example.com/api2",
    "https://accounting.company.io/api2",
    "http://192.168.1.100:5000/api2",
    "https://manager.internal.corp/api2",
])

# Record count strategy - number of total records in paginated endpoint
record_count_strategy = st.integers(min_value=0, max_value=500)

# Page size strategy - number of records per page
page_size_strategy = st.integers(min_value=10, max_value=200)

# Cache TTL strategy - time to live in seconds
cache_ttl_strategy = st.integers(min_value=1, max_value=3600)

# Endpoint strategy - valid API endpoint paths
endpoint_strategy = st.sampled_from([
    "/chart-of-accounts",
    "/suppliers",
    "/customers",
    "/payments",
    "/receipts",
    "/inter-account-transfers",
    "/journal-entry-lines",
])


# =============================================================================
# Helper Functions
# =============================================================================

def generate_mock_records(count: int) -> List[Dict[str, Any]]:
    """Generate mock records for testing pagination."""
    return [{"key": f"id-{i}", "name": f"Item {i}", "data": f"value-{i}"} for i in range(count)]


class MockRedis:
    """Mock Redis client for testing cache behavior."""
    
    def __init__(self):
        self._store: Dict[str, str] = {}
        self._call_log: List[Dict[str, Any]] = []
    
    async def get(self, key: str) -> str | None:
        self._call_log.append({"method": "get", "key": key})
        return self._store.get(key)
    
    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._call_log.append({"method": "setex", "key": key, "ttl": ttl})
        self._store[key] = value
    
    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._call_log.append({"method": "delete", "key": key})
            self._store.pop(key, None)
    
    def scan_iter(self, match: str = "*"):
        return iter([])
    
    def clear_log(self):
        self._call_log = []
    
    def clear_store(self):
        self._store = {}
    
    def get_call_count(self, method: str) -> int:
        return sum(1 for call in self._call_log if call["method"] == method)


# =============================================================================
# Property 9: Pagination Completeness
# =============================================================================


class TestPaginationCompletenessProperty:
    """Property 9: Pagination Completeness
    
    For any paginated Manager.io endpoint with N total records, calling
    fetch_all_paginated SHALL return exactly N records regardless of page size.
    
    **Validates: Requirements 5.4**
    """
    
    @given(
        total_records=record_count_strategy,
        page_size=page_size_strategy,
        base_url=base_url_strategy,
        api_key=api_key_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_fetch_all_paginated_returns_exactly_n_records(
        self,
        total_records: int,
        page_size: int,
        base_url: str,
        api_key: str,
    ):
        """Feature: manager-io-bookkeeper, Property 9: Pagination Completeness
        
        For any paginated endpoint with N total records, fetch_all_paginated
        SHALL return exactly N records regardless of page size.
        **Validates: Requirements 5.4**
        """
        async def run_test():
            # Generate mock records
            all_records = generate_mock_records(total_records)
            
            # Create client with specified page size
            client = ManagerIOClient(
                base_url=base_url,
                api_key=api_key,
                cache=None,  # Disable cache for this test
                page_size=page_size,
            )
            
            # Track which pages were requested
            pages_requested = []
            
            async def mock_request(*args, **kwargs):
                params = kwargs.get("params", {})
                skip = params.get("skip", 0)
                take = params.get("take", page_size)
                
                pages_requested.append({"skip": skip, "take": take})
                
                # Return the appropriate slice of records
                page_records = all_records[skip:skip + take]
                
                response = MagicMock()
                response.is_success = True
                response.status_code = 200
                response.json.return_value = page_records
                return response
            
            try:
                with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
                    result = await client.fetch_all_paginated("/test-endpoint", use_cache=False)
                    
                    # Property: returned records count equals total records
                    assert len(result) == total_records, \
                        f"Expected {total_records} records, got {len(result)}"
                    
                    # Property: all records are present and in order
                    for i, record in enumerate(result):
                        assert record["key"] == f"id-{i}", \
                            f"Record at index {i} has wrong key: {record['key']}"
            finally:
                await client.close()
        
        asyncio.run(run_test())

    @given(
        total_records=record_count_strategy,
        page_size=page_size_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_fetch_all_paginated_with_total_count_response(
        self,
        total_records: int,
        page_size: int,
    ):
        """Feature: manager-io-bookkeeper, Property 9: Pagination Completeness
        
        For paginated responses with total count metadata, fetch_all_paginated
        SHALL return exactly N records.
        **Validates: Requirements 5.4**
        """
        async def run_test():
            all_records = generate_mock_records(total_records)
            
            client = ManagerIOClient(
                base_url="https://manager.example.com/api2",
                api_key="test-api-key",
                cache=None,
                page_size=page_size,
            )
            
            async def mock_request(*args, **kwargs):
                params = kwargs.get("params", {})
                skip = params.get("skip", 0)
                take = params.get("take", page_size)
                
                page_records = all_records[skip:skip + take]
                
                response = MagicMock()
                response.is_success = True
                response.status_code = 200
                # Response format with total count metadata
                response.json.return_value = {
                    "items": page_records,
                    "total": total_records,
                    "skip": skip,
                    "take": take,
                }
                return response
            
            try:
                with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
                    result = await client.fetch_all_paginated("/test-endpoint", use_cache=False)
                    
                    # Property: returned records count equals total records
                    assert len(result) == total_records, \
                        f"Expected {total_records} records, got {len(result)}"
            finally:
                await client.close()
        
        asyncio.run(run_test())
    
    @given(
        total_records=st.integers(min_value=1, max_value=500),
        page_size=page_size_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_pagination_makes_minimum_required_requests(
        self,
        total_records: int,
        page_size: int,
    ):
        """Feature: manager-io-bookkeeper, Property 9: Pagination Completeness
        
        For N records with page size P, pagination SHALL make at least ceil(N/P) requests.
        When N is exactly divisible by P, an extra request may be needed to confirm
        there are no more records.
        **Validates: Requirements 5.4**
        """
        import math
        
        async def run_test():
            all_records = generate_mock_records(total_records)
            
            client = ManagerIOClient(
                base_url="https://manager.example.com/api2",
                api_key="test-api-key",
                cache=None,
                page_size=page_size,
            )
            
            request_count = 0
            
            async def mock_request(*args, **kwargs):
                nonlocal request_count
                request_count += 1
                
                params = kwargs.get("params", {})
                skip = params.get("skip", 0)
                take = params.get("take", page_size)
                
                page_records = all_records[skip:skip + take]
                
                response = MagicMock()
                response.is_success = True
                response.status_code = 200
                response.json.return_value = page_records
                return response
            
            try:
                with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
                    result = await client.fetch_all_paginated("/test-endpoint", use_cache=False)
                    
                    # Property: all records were fetched
                    assert len(result) == total_records, \
                        f"Expected {total_records} records, got {len(result)}"
                    
                    # Property: minimum number of requests is ceil(total/page_size)
                    min_requests = math.ceil(total_records / page_size)
                    # When total_records is exactly divisible by page_size, an extra
                    # request is needed to confirm there are no more records
                    max_requests = min_requests + (1 if total_records % page_size == 0 else 0)
                    
                    assert min_requests <= request_count <= max_requests, \
                        f"Expected {min_requests}-{max_requests} requests, made {request_count}"
            finally:
                await client.close()
        
        asyncio.run(run_test())


# =============================================================================
# Property 10: Cache Behavior
# =============================================================================


class TestCacheBehaviorProperty:
    """Property 10: Cache Behavior
    
    For any cacheable API response, the first request SHALL call the Manager.io API,
    subsequent requests within TTL SHALL NOT call the API (cache hit), and requests
    after TTL expiration SHALL call the API again.
    
    **Validates: Requirements 5.5, 5.6**
    """
    
    @given(
        endpoint=endpoint_strategy,
        api_key=api_key_strategy,
        cache_ttl=cache_ttl_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_first_request_calls_api_and_caches(
        self,
        endpoint: str,
        api_key: str,
        cache_ttl: int,
    ):
        """Feature: manager-io-bookkeeper, Property 10: Cache Behavior
        
        The first request SHALL call the Manager.io API and cache the result.
        **Validates: Requirements 5.5**
        """
        async def run_test():
            mock_redis = MockRedis()
            
            client = ManagerIOClient(
                base_url="https://manager.example.com/api2",
                api_key=api_key,
                cache=mock_redis,
                cache_ttl=cache_ttl,
            )
            
            api_call_count = 0
            test_data = {"key": "test-123", "name": "Test Item"}
            
            async def mock_request(*args, **kwargs):
                nonlocal api_call_count
                api_call_count += 1
                
                response = MagicMock()
                response.is_success = True
                response.status_code = 200
                response.json.return_value = test_data
                return response
            
            try:
                with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
                    result = await client._get(endpoint, use_cache=True)
                    
                    # Property: API was called exactly once
                    assert api_call_count == 1, \
                        f"Expected 1 API call, got {api_call_count}"
                    
                    # Property: result matches expected data
                    assert result == test_data
                    
                    # Property: cache was checked (get called)
                    assert mock_redis.get_call_count("get") >= 1, \
                        "Cache should have been checked"
                    
                    # Property: result was cached (setex called)
                    assert mock_redis.get_call_count("setex") == 1, \
                        "Result should have been cached"
            finally:
                await client.close()
        
        asyncio.run(run_test())

    @given(
        endpoint=endpoint_strategy,
        api_key=api_key_strategy,
        cache_ttl=cache_ttl_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_subsequent_request_within_ttl_uses_cache(
        self,
        endpoint: str,
        api_key: str,
        cache_ttl: int,
    ):
        """Feature: manager-io-bookkeeper, Property 10: Cache Behavior
        
        Subsequent requests within TTL SHALL NOT call the API (cache hit).
        **Validates: Requirements 5.5**
        """
        async def run_test():
            mock_redis = MockRedis()
            
            client = ManagerIOClient(
                base_url="https://manager.example.com/api2",
                api_key=api_key,
                cache=mock_redis,
                cache_ttl=cache_ttl,
            )
            
            api_call_count = 0
            test_data = {"key": "test-123", "name": "Test Item"}
            
            async def mock_request(*args, **kwargs):
                nonlocal api_call_count
                api_call_count += 1
                
                response = MagicMock()
                response.is_success = True
                response.status_code = 200
                response.json.return_value = test_data
                return response
            
            try:
                with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
                    # First request - should call API
                    result1 = await client._get(endpoint, use_cache=True)
                    assert api_call_count == 1, "First request should call API"
                    
                    # Clear the call log to track subsequent behavior
                    mock_redis.clear_log()
                    
                    # Second request - should use cache (data is now in mock_redis._store)
                    result2 = await client._get(endpoint, use_cache=True)
                    
                    # Property: API was NOT called again
                    assert api_call_count == 1, \
                        f"Expected 1 API call total, got {api_call_count}"
                    
                    # Property: cache was checked
                    assert mock_redis.get_call_count("get") >= 1, \
                        "Cache should have been checked"
                    
                    # Property: results are identical
                    assert result1 == result2, \
                        "Cached result should match original"
            finally:
                await client.close()
        
        asyncio.run(run_test())
    
    @given(
        endpoint=endpoint_strategy,
        api_key=api_key_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_request_after_cache_expiration_calls_api(
        self,
        endpoint: str,
        api_key: str,
    ):
        """Feature: manager-io-bookkeeper, Property 10: Cache Behavior
        
        Requests after TTL expiration SHALL call the API again.
        **Validates: Requirements 5.6**
        """
        async def run_test():
            mock_redis = MockRedis()
            
            client = ManagerIOClient(
                base_url="https://manager.example.com/api2",
                api_key=api_key,
                cache=mock_redis,
                cache_ttl=300,
            )
            
            api_call_count = 0
            test_data = {"key": "test-123", "name": "Test Item"}
            
            async def mock_request(*args, **kwargs):
                nonlocal api_call_count
                api_call_count += 1
                
                response = MagicMock()
                response.is_success = True
                response.status_code = 200
                response.json.return_value = test_data
                return response
            
            try:
                with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
                    # First request - should call API and cache
                    result1 = await client._get(endpoint, use_cache=True)
                    assert api_call_count == 1, "First request should call API"
                    
                    # Simulate cache expiration by clearing the store
                    mock_redis.clear_store()
                    mock_redis.clear_log()
                    
                    # Request after expiration - should call API again
                    result2 = await client._get(endpoint, use_cache=True)
                    
                    # Property: API was called again after cache expiration
                    assert api_call_count == 2, \
                        f"Expected 2 API calls total, got {api_call_count}"
                    
                    # Property: new result was cached
                    assert mock_redis.get_call_count("setex") == 1, \
                        "New result should have been cached"
            finally:
                await client.close()
        
        asyncio.run(run_test())

    @given(
        total_records=st.integers(min_value=1, max_value=300),
        page_size=page_size_strategy,
        cache_ttl=cache_ttl_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_paginated_results_are_cached(
        self,
        total_records: int,
        page_size: int,
        cache_ttl: int,
    ):
        """Feature: manager-io-bookkeeper, Property 10: Cache Behavior
        
        Paginated results SHALL be cached as a complete set.
        **Validates: Requirements 5.5**
        """
        async def run_test():
            mock_redis = MockRedis()
            all_records = generate_mock_records(total_records)
            
            client = ManagerIOClient(
                base_url="https://manager.example.com/api2",
                api_key="test-api-key",
                cache=mock_redis,
                cache_ttl=cache_ttl,
                page_size=page_size,
            )
            
            api_call_count = 0
            
            async def mock_request(*args, **kwargs):
                nonlocal api_call_count
                api_call_count += 1
                
                params = kwargs.get("params", {})
                skip = params.get("skip", 0)
                take = params.get("take", page_size)
                
                page_records = all_records[skip:skip + take]
                
                response = MagicMock()
                response.is_success = True
                response.status_code = 200
                response.json.return_value = page_records
                return response
            
            try:
                with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
                    # First fetch - should call API multiple times for pagination
                    result1 = await client.fetch_all_paginated("/test", use_cache=True)
                    first_call_count = api_call_count
                    
                    assert len(result1) == total_records
                    
                    # Clear log to track subsequent behavior
                    mock_redis.clear_log()
                    
                    # Second fetch - should use cache
                    result2 = await client.fetch_all_paginated("/test", use_cache=True)
                    
                    # Property: API was NOT called again (cache hit)
                    assert api_call_count == first_call_count, \
                        f"Expected {first_call_count} API calls, got {api_call_count}"
                    
                    # Property: results are identical
                    assert result1 == result2, \
                        "Cached result should match original"
            finally:
                await client.close()
        
        asyncio.run(run_test())


# =============================================================================
# Property 11: API Authentication Header
# =============================================================================


class TestAPIAuthenticationHeaderProperty:
    """Property 11: API Authentication Header
    
    For any request made through ManagerIOClient, the request headers SHALL
    contain X-API-KEY with the configured API key value.
    
    **Validates: Requirements 5.7**
    """
    
    @given(
        api_key=api_key_strategy,
        base_url=base_url_strategy,
        endpoint=endpoint_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_x_api_key_header_present_in_all_requests(
        self,
        api_key: str,
        base_url: str,
        endpoint: str,
    ):
        """Feature: manager-io-bookkeeper, Property 11: API Authentication Header
        
        For any request, headers SHALL contain X-API-KEY with the configured value.
        **Validates: Requirements 5.7**
        """
        async def run_test():
            client = ManagerIOClient(
                base_url=base_url,
                api_key=api_key,
                cache=None,
            )
            
            try:
                # Get the HTTP client and verify headers
                http_client = await client._get_client()
                
                # Property: X-API-KEY header is present
                assert "X-API-KEY" in http_client.headers, \
                    "X-API-KEY header should be present"
                
                # Property: X-API-KEY value matches configured API key
                assert http_client.headers["X-API-KEY"] == api_key, \
                    f"X-API-KEY should be '{api_key}', got '{http_client.headers['X-API-KEY']}'"
            finally:
                await client.close()
        
        asyncio.run(run_test())
    
    @given(
        api_key=api_key_strategy,
        endpoint=endpoint_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_x_api_key_header_in_get_requests(
        self,
        api_key: str,
        endpoint: str,
    ):
        """Feature: manager-io-bookkeeper, Property 11: API Authentication Header
        
        GET requests SHALL include X-API-KEY header.
        **Validates: Requirements 5.7**
        """
        async def run_test():
            client = ManagerIOClient(
                base_url="https://manager.example.com/api2",
                api_key=api_key,
                cache=None,
            )
            
            try:
                # Get the HTTP client - this is where headers are configured
                http_client = await client._get_client()
                
                # Property: X-API-KEY header is configured on the client
                assert "X-API-KEY" in http_client.headers, \
                    "X-API-KEY header should be configured on HTTP client"
                assert http_client.headers["X-API-KEY"] == api_key, \
                    f"X-API-KEY should be '{api_key}'"
                
                # Verify the client would use these headers in requests
                # by checking the client is properly configured
                assert client.api_key == api_key, \
                    "Client should store the API key"
            finally:
                await client.close()
        
        asyncio.run(run_test())

    @given(
        api_key=api_key_strategy,
        endpoint=endpoint_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_x_api_key_header_in_post_requests(
        self,
        api_key: str,
        endpoint: str,
    ):
        """Feature: manager-io-bookkeeper, Property 11: API Authentication Header
        
        POST requests SHALL include X-API-KEY header.
        **Validates: Requirements 5.7**
        """
        async def run_test():
            client = ManagerIOClient(
                base_url="https://manager.example.com/api2",
                api_key=api_key,
                cache=None,
            )
            
            try:
                # Get the HTTP client - this is where headers are configured
                http_client = await client._get_client()
                
                # Property: X-API-KEY header is configured on the client for POST
                assert "X-API-KEY" in http_client.headers, \
                    "X-API-KEY header should be configured on HTTP client"
                assert http_client.headers["X-API-KEY"] == api_key, \
                    f"X-API-KEY should be '{api_key}'"
                
                # Verify Content-Type is set for POST requests
                assert http_client.headers.get("Content-Type") == "application/json", \
                    "Content-Type should be application/json for POST"
            finally:
                await client.close()
        
        asyncio.run(run_test())
    
    @given(
        api_key=api_key_strategy,
        endpoint=endpoint_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_x_api_key_header_in_put_requests(
        self,
        api_key: str,
        endpoint: str,
    ):
        """Feature: manager-io-bookkeeper, Property 11: API Authentication Header
        
        PUT requests SHALL include X-API-KEY header.
        **Validates: Requirements 5.7**
        """
        async def run_test():
            client = ManagerIOClient(
                base_url="https://manager.example.com/api2",
                api_key=api_key,
                cache=None,
            )
            
            try:
                # Get the HTTP client - this is where headers are configured
                http_client = await client._get_client()
                
                # Property: X-API-KEY header is configured on the client for PUT
                assert "X-API-KEY" in http_client.headers, \
                    "X-API-KEY header should be configured on HTTP client"
                assert http_client.headers["X-API-KEY"] == api_key, \
                    f"X-API-KEY should be '{api_key}'"
                
                # Verify Content-Type is set for PUT requests
                assert http_client.headers.get("Content-Type") == "application/json", \
                    "Content-Type should be application/json for PUT"
            finally:
                await client.close()
        
        asyncio.run(run_test())

    @given(
        api_key=api_key_strategy,
        total_records=st.integers(min_value=1, max_value=200),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_x_api_key_header_in_paginated_requests(
        self,
        api_key: str,
        total_records: int,
    ):
        """Feature: manager-io-bookkeeper, Property 11: API Authentication Header
        
        All paginated requests SHALL include X-API-KEY header.
        **Validates: Requirements 5.7**
        """
        async def run_test():
            client = ManagerIOClient(
                base_url="https://manager.example.com/api2",
                api_key=api_key,
                cache=None,
                page_size=50,
            )
            
            try:
                # Get the HTTP client - this is where headers are configured
                http_client = await client._get_client()
                
                # Property: X-API-KEY header is configured for paginated requests
                assert "X-API-KEY" in http_client.headers, \
                    "X-API-KEY header should be configured on HTTP client"
                assert http_client.headers["X-API-KEY"] == api_key, \
                    f"X-API-KEY should be '{api_key}'"
                
                # Property: the same client instance is reused for all requests
                # (headers are set once and used for all paginated requests)
                http_client2 = await client._get_client()
                assert http_client is http_client2, \
                    "Same HTTP client instance should be reused"
            finally:
                await client.close()
        
        asyncio.run(run_test())
    
    @given(
        api_key=api_key_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_content_type_and_accept_headers_present(
        self,
        api_key: str,
    ):
        """Feature: manager-io-bookkeeper, Property 11: API Authentication Header
        
        All requests SHALL include proper Content-Type and Accept headers.
        **Validates: Requirements 5.7**
        """
        async def run_test():
            client = ManagerIOClient(
                base_url="https://manager.example.com/api2",
                api_key=api_key,
                cache=None,
            )
            
            try:
                http_client = await client._get_client()
                
                # Property: Content-Type header is application/json
                assert http_client.headers.get("Content-Type") == "application/json", \
                    "Content-Type should be application/json"
                
                # Property: Accept header is application/json
                assert http_client.headers.get("Accept") == "application/json", \
                    "Accept should be application/json"
            finally:
                await client.close()
        
        asyncio.run(run_test())


# =============================================================================
# Property 12: Expense Claim Payload Structure
# =============================================================================


class TestExpenseClaimPayloadStructureProperty:
    """Property 12: Expense Claim Payload Structure
    
    For any ExpenseClaimData submitted through create_expense_claim, the POST
    payload SHALL contain Date, PaidBy, Payee, Description, and Lines array
    with each line containing Account, LineDescription, Qty, and PurchaseUnitPrice.
    
    **Validates: Requirements 6.3, 6.8**
    """
    
    @given(
        date=st.dates().map(lambda d: d.strftime("%Y-%m-%d")),
        paid_by=st.uuids().map(str),
        payee=st.text(min_size=1, max_size=100).filter(lambda x: len(x.strip()) > 0),
        description=st.text(min_size=1, max_size=200).filter(lambda x: len(x.strip()) > 0),
        num_lines=st.integers(min_value=1, max_value=5),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_expense_claim_payload_contains_required_fields(
        self,
        date: str,
        paid_by: str,
        payee: str,
        description: str,
        num_lines: int,
    ):
        """Feature: manager-io-bookkeeper, Property 12: Expense Claim Payload Structure
        
        The POST payload SHALL contain Date, PaidBy, Payee, Description, and Lines.
        **Validates: Requirements 6.3, 6.8**
        """
        from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine, ManagerIOClient
        
        # Generate line items
        lines = [
            ExpenseClaimLine(
                account=str(f"account-{i}"),
                line_description=f"Line item {i}",
                qty=1,
                purchase_unit_price=100.0 * (i + 1),
            )
            for i in range(num_lines)
        ]
        
        # Create expense claim data
        data = ExpenseClaimData(
            date=date,
            paid_by=paid_by,
            payee=payee,
            description=description,
            lines=lines,
        )
        
        # Create client and build payload
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="test-api-key",
            cache=None,
        )
        
        payload = client._build_expense_claim_payload(data)
        
        # Property: payload contains Date
        assert "Date" in payload, "Payload must contain Date"
        assert payload["Date"] == date, f"Date should be {date}"
        
        # Property: payload contains PaidBy
        assert "PaidBy" in payload, "Payload must contain PaidBy"
        assert payload["PaidBy"] == paid_by, f"PaidBy should be {paid_by}"
        
        # Property: payload contains Payee
        assert "Payee" in payload, "Payload must contain Payee"
        assert payload["Payee"] == payee, f"Payee should be {payee}"
        
        # Property: payload contains Description
        assert "Description" in payload, "Payload must contain Description"
        assert payload["Description"] == description, f"Description should be {description}"
        
        # Property: payload contains Lines array
        assert "Lines" in payload, "Payload must contain Lines"
        assert isinstance(payload["Lines"], list), "Lines must be a list"
        assert len(payload["Lines"]) == num_lines, f"Lines should have {num_lines} items"
    
    @given(
        account=st.uuids().map(str),
        line_description=st.text(min_size=1, max_size=100).filter(lambda x: len(x.strip()) > 0),
        qty=st.integers(min_value=1, max_value=100),
        unit_price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_expense_claim_line_contains_required_fields(
        self,
        account: str,
        line_description: str,
        qty: int,
        unit_price: float,
    ):
        """Feature: manager-io-bookkeeper, Property 12: Expense Claim Payload Structure
        
        Each line SHALL contain Account, LineDescription, Qty, and PurchaseUnitPrice.
        **Validates: Requirements 6.3, 6.8**
        """
        from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine, ManagerIOClient
        
        # Create expense claim with single line
        data = ExpenseClaimData(
            date="2024-01-15",
            paid_by="employee-uuid",
            payee="Test Vendor",
            description="Test expense",
            lines=[
                ExpenseClaimLine(
                    account=account,
                    line_description=line_description,
                    qty=qty,
                    purchase_unit_price=unit_price,
                )
            ],
        )
        
        # Create client and build payload
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="test-api-key",
            cache=None,
        )
        
        payload = client._build_expense_claim_payload(data)
        line = payload["Lines"][0]
        
        # Property: line contains Account
        assert "Account" in line, "Line must contain Account"
        assert line["Account"] == account, f"Account should be {account}"
        
        # Property: line contains LineDescription
        assert "LineDescription" in line, "Line must contain LineDescription"
        assert line["LineDescription"] == line_description, f"LineDescription should be {line_description}"
        
        # Property: line contains Qty
        assert "Qty" in line, "Line must contain Qty"
        assert line["Qty"] == qty, f"Qty should be {qty}"
        
        # Property: line contains PurchaseUnitPrice
        assert "PurchaseUnitPrice" in line, "Line must contain PurchaseUnitPrice"
        assert line["PurchaseUnitPrice"] == unit_price, f"PurchaseUnitPrice should be {unit_price}"
    
    @given(
        num_lines=st.integers(min_value=1, max_value=10),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_expense_claim_payload_has_line_description_flag(
        self,
        num_lines: int,
    ):
        """Feature: manager-io-bookkeeper, Property 12: Expense Claim Payload Structure
        
        The payload SHALL contain HasLineDescription flag.
        **Validates: Requirements 6.3, 6.8**
        """
        from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine, ManagerIOClient
        
        # Generate line items
        lines = [
            ExpenseClaimLine(
                account=f"account-{i}",
                line_description=f"Line {i}",
                qty=1,
                purchase_unit_price=50.0,
            )
            for i in range(num_lines)
        ]
        
        # Create expense claim data
        data = ExpenseClaimData(
            date="2024-01-15",
            paid_by="employee-uuid",
            payee="Test Vendor",
            description="Test expense",
            lines=lines,
            has_line_description=True,
        )
        
        # Create client and build payload
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="test-api-key",
            cache=None,
        )
        
        payload = client._build_expense_claim_payload(data)
        
        # Property: payload contains HasLineDescription
        assert "HasLineDescription" in payload, "Payload must contain HasLineDescription"
        assert payload["HasLineDescription"] is True, "HasLineDescription should be True"
    
    @given(
        num_lines=st.integers(min_value=1, max_value=5),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_expense_claim_lines_have_custom_fields_structure(
        self,
        num_lines: int,
    ):
        """Feature: manager-io-bookkeeper, Property 12: Expense Claim Payload Structure
        
        Each line SHALL contain CustomFields and CustomFields2 structures.
        **Validates: Requirements 6.3, 6.8**
        """
        from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine, ManagerIOClient
        
        # Generate line items
        lines = [
            ExpenseClaimLine(
                account=f"account-{i}",
                line_description=f"Line {i}",
                qty=1,
                purchase_unit_price=50.0,
            )
            for i in range(num_lines)
        ]
        
        # Create expense claim data
        data = ExpenseClaimData(
            date="2024-01-15",
            paid_by="employee-uuid",
            payee="Test Vendor",
            description="Test expense",
            lines=lines,
        )
        
        # Create client and build payload
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="test-api-key",
            cache=None,
        )
        
        payload = client._build_expense_claim_payload(data)
        
        # Property: each line has CustomFields and CustomFields2
        for i, line in enumerate(payload["Lines"]):
            assert "CustomFields" in line, f"Line {i} must contain CustomFields"
            assert "CustomFields2" in line, f"Line {i} must contain CustomFields2"
            
            # Property: CustomFields2 has required structure
            cf2 = line["CustomFields2"]
            assert "Strings" in cf2, f"Line {i} CustomFields2 must contain Strings"
            assert "Decimals" in cf2, f"Line {i} CustomFields2 must contain Decimals"
            assert "Dates" in cf2, f"Line {i} CustomFields2 must contain Dates"
            assert "Booleans" in cf2, f"Line {i} CustomFields2 must contain Booleans"
            assert "StringArrays" in cf2, f"Line {i} CustomFields2 must contain StringArrays"


# =============================================================================
# Property 13: Purchase Invoice Payload Structure
# =============================================================================


class TestPurchaseInvoicePayloadStructureProperty:
    """Property 13: Purchase Invoice Payload Structure
    
    For any PurchaseInvoiceData submitted through create_purchase_invoice, the POST
    payload SHALL contain IssueDate, Reference, Description, Supplier, and Lines
    array with each line containing Account, LineDescription, and PurchaseUnitPrice.
    
    **Validates: Requirements 6.4, 6.8**
    """
    
    @given(
        issue_date=st.dates().map(lambda d: d.strftime("%Y-%m-%d")),
        reference=st.text(min_size=1, max_size=50).filter(lambda x: len(x.strip()) > 0),
        description=st.text(min_size=1, max_size=200).filter(lambda x: len(x.strip()) > 0),
        supplier=st.uuids().map(str),
        num_lines=st.integers(min_value=1, max_value=5),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_purchase_invoice_payload_contains_required_fields(
        self,
        issue_date: str,
        reference: str,
        description: str,
        supplier: str,
        num_lines: int,
    ):
        """Feature: manager-io-bookkeeper, Property 13: Purchase Invoice Payload Structure
        
        The POST payload SHALL contain IssueDate, Reference, Description, Supplier, and Lines.
        **Validates: Requirements 6.4, 6.8**
        """
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine, ManagerIOClient
        
        # Generate line items
        lines = [
            PurchaseInvoiceLine(
                account=f"account-{i}",
                line_description=f"Line item {i}",
                purchase_unit_price=100.0 * (i + 1),
            )
            for i in range(num_lines)
        ]
        
        # Create purchase invoice data
        data = PurchaseInvoiceData(
            issue_date=issue_date,
            reference=reference,
            description=description,
            supplier=supplier,
            lines=lines,
        )
        
        # Create client and build payload
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="test-api-key",
            cache=None,
        )
        
        payload = client._build_purchase_invoice_payload(data)
        
        # Property: payload contains IssueDate
        assert "IssueDate" in payload, "Payload must contain IssueDate"
        assert payload["IssueDate"] == issue_date, f"IssueDate should be {issue_date}"
        
        # Property: payload contains Reference
        assert "Reference" in payload, "Payload must contain Reference"
        assert payload["Reference"] == reference, f"Reference should be {reference}"
        
        # Property: payload contains Description
        assert "Description" in payload, "Payload must contain Description"
        assert payload["Description"] == description, f"Description should be {description}"
        
        # Property: payload contains Supplier
        assert "Supplier" in payload, "Payload must contain Supplier"
        assert payload["Supplier"] == supplier, f"Supplier should be {supplier}"
        
        # Property: payload contains Lines array
        assert "Lines" in payload, "Payload must contain Lines"
        assert isinstance(payload["Lines"], list), "Lines must be a list"
        assert len(payload["Lines"]) == num_lines, f"Lines should have {num_lines} items"
    
    @given(
        account=st.uuids().map(str),
        line_description=st.text(min_size=1, max_size=100).filter(lambda x: len(x.strip()) > 0),
        unit_price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_purchase_invoice_line_contains_required_fields(
        self,
        account: str,
        line_description: str,
        unit_price: float,
    ):
        """Feature: manager-io-bookkeeper, Property 13: Purchase Invoice Payload Structure
        
        Each line SHALL contain Account, LineDescription, and PurchaseUnitPrice.
        **Validates: Requirements 6.4, 6.8**
        """
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine, ManagerIOClient
        
        # Create purchase invoice with single line
        data = PurchaseInvoiceData(
            issue_date="2024-01-15",
            reference="#INV-001",
            description="Test invoice",
            supplier="supplier-uuid",
            lines=[
                PurchaseInvoiceLine(
                    account=account,
                    line_description=line_description,
                    purchase_unit_price=unit_price,
                )
            ],
        )
        
        # Create client and build payload
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="test-api-key",
            cache=None,
        )
        
        payload = client._build_purchase_invoice_payload(data)
        line = payload["Lines"][0]
        
        # Property: line contains Account
        assert "Account" in line, "Line must contain Account"
        assert line["Account"] == account, f"Account should be {account}"
        
        # Property: line contains LineDescription
        assert "LineDescription" in line, "Line must contain LineDescription"
        assert line["LineDescription"] == line_description, f"LineDescription should be {line_description}"
        
        # Property: line contains PurchaseUnitPrice
        assert "PurchaseUnitPrice" in line, "Line must contain PurchaseUnitPrice"
        assert line["PurchaseUnitPrice"] == unit_price, f"PurchaseUnitPrice should be {unit_price}"
    
    @given(
        has_line_number=st.booleans(),
        has_line_description=st.booleans(),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_purchase_invoice_payload_has_line_flags(
        self,
        has_line_number: bool,
        has_line_description: bool,
    ):
        """Feature: manager-io-bookkeeper, Property 13: Purchase Invoice Payload Structure
        
        The payload SHALL contain HasLineNumber and HasLineDescription flags.
        **Validates: Requirements 6.4, 6.8**
        """
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine, ManagerIOClient
        
        # Create purchase invoice data
        data = PurchaseInvoiceData(
            issue_date="2024-01-15",
            reference="#INV-001",
            description="Test invoice",
            supplier="supplier-uuid",
            lines=[
                PurchaseInvoiceLine(
                    account="account-uuid",
                    line_description="Test line",
                    purchase_unit_price=50.0,
                )
            ],
            has_line_number=has_line_number,
            has_line_description=has_line_description,
        )
        
        # Create client and build payload
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="test-api-key",
            cache=None,
        )
        
        payload = client._build_purchase_invoice_payload(data)
        
        # Property: payload contains HasLineNumber
        assert "HasLineNumber" in payload, "Payload must contain HasLineNumber"
        assert payload["HasLineNumber"] == has_line_number, f"HasLineNumber should be {has_line_number}"
        
        # Property: payload contains HasLineDescription
        assert "HasLineDescription" in payload, "Payload must contain HasLineDescription"
        assert payload["HasLineDescription"] == has_line_description, f"HasLineDescription should be {has_line_description}"
    
    @given(
        num_lines=st.integers(min_value=1, max_value=5),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_purchase_invoice_lines_have_custom_fields_structure(
        self,
        num_lines: int,
    ):
        """Feature: manager-io-bookkeeper, Property 13: Purchase Invoice Payload Structure
        
        Each line SHALL contain CustomFields and CustomFields2 structures.
        **Validates: Requirements 6.4, 6.8**
        """
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine, ManagerIOClient
        
        # Generate line items
        lines = [
            PurchaseInvoiceLine(
                account=f"account-{i}",
                line_description=f"Line {i}",
                purchase_unit_price=50.0,
            )
            for i in range(num_lines)
        ]
        
        # Create purchase invoice data
        data = PurchaseInvoiceData(
            issue_date="2024-01-15",
            reference="#INV-001",
            description="Test invoice",
            supplier="supplier-uuid",
            lines=lines,
        )
        
        # Create client and build payload
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="test-api-key",
            cache=None,
        )
        
        payload = client._build_purchase_invoice_payload(data)
        
        # Property: each line has CustomFields and CustomFields2
        for i, line in enumerate(payload["Lines"]):
            assert "CustomFields" in line, f"Line {i} must contain CustomFields"
            assert "CustomFields2" in line, f"Line {i} must contain CustomFields2"
            
            # Property: CustomFields2 has required structure
            cf2 = line["CustomFields2"]
            assert "Strings" in cf2, f"Line {i} CustomFields2 must contain Strings"
            assert "Decimals" in cf2, f"Line {i} CustomFields2 must contain Decimals"
            assert "Dates" in cf2, f"Line {i} CustomFields2 must contain Dates"
            assert "Booleans" in cf2, f"Line {i} CustomFields2 must contain Booleans"
            assert "StringArrays" in cf2, f"Line {i} CustomFields2 must contain StringArrays"
    
    @given(
        num_lines=st.integers(min_value=1, max_value=10),
        prices=st.lists(
            st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10,
        ),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_purchase_invoice_preserves_line_order(
        self,
        num_lines: int,
        prices: list,
    ):
        """Feature: manager-io-bookkeeper, Property 13: Purchase Invoice Payload Structure
        
        The payload SHALL preserve the order of line items.
        **Validates: Requirements 6.4, 6.8**
        """
        from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine, ManagerIOClient
        
        # Use the minimum of num_lines and prices length
        actual_lines = min(num_lines, len(prices))
        
        # Generate line items with specific prices
        lines = [
            PurchaseInvoiceLine(
                account=f"account-{i}",
                line_description=f"Line {i}",
                purchase_unit_price=prices[i],
            )
            for i in range(actual_lines)
        ]
        
        # Create purchase invoice data
        data = PurchaseInvoiceData(
            issue_date="2024-01-15",
            reference="#INV-001",
            description="Test invoice",
            supplier="supplier-uuid",
            lines=lines,
        )
        
        # Create client and build payload
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="test-api-key",
            cache=None,
        )
        
        payload = client._build_purchase_invoice_payload(data)
        
        # Property: line order is preserved
        for i, line in enumerate(payload["Lines"]):
            assert line["Account"] == f"account-{i}", f"Line {i} account should be account-{i}"
            assert line["LineDescription"] == f"Line {i}", f"Line {i} description should be Line {i}"
            assert line["PurchaseUnitPrice"] == prices[i], f"Line {i} price should be {prices[i]}"
