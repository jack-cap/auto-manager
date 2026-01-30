"""Manager.io API client for data fetching and entry submission.

This module provides the ManagerIOClient class for interacting with the
Manager.io accounting software API. It includes:
- HTTP client with X-API-KEY authentication
- Pagination helper for fetching all records
- Redis caching with configurable TTL
- Error handling with exponential backoff retry logic
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Generic, List, Optional, TypeVar

import httpx
from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Data Models
# =============================================================================


class Account(BaseModel):
    """Manager.io account from chart of accounts."""
    key: str
    name: str
    code: Optional[str] = None


class Supplier(BaseModel):
    """Manager.io supplier."""
    key: str
    name: str


class Customer(BaseModel):
    """Manager.io customer."""
    key: str
    name: str


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response from Manager.io API."""
    items: List[Any]
    total: int
    skip: int
    take: int


class ExpenseClaimLine(BaseModel):
    """Line item for expense claim."""
    account: str  # Account key (UUID)
    line_description: str
    qty: int = 1
    purchase_unit_price: float


class ExpenseClaimData(BaseModel):
    """Data for creating an expense claim."""
    date: str  # YYYY-MM-DD
    paid_by: str  # Employee key
    payee: str
    description: str
    lines: List[ExpenseClaimLine]
    has_line_description: bool = True


class PurchaseInvoiceLine(BaseModel):
    """Line item for purchase invoice."""
    account: str  # Account key (UUID)
    line_description: str
    purchase_unit_price: float


class PurchaseInvoiceData(BaseModel):
    """Data for creating a purchase invoice."""
    issue_date: str  # YYYY-MM-DD
    reference: str
    description: str
    supplier: str  # Supplier key
    lines: List[PurchaseInvoiceLine]
    has_line_number: bool = True
    has_line_description: bool = True


class SalesInvoiceLine(BaseModel):
    """Line item for sales invoice."""
    account: str  # Income account key (UUID)
    line_description: str
    qty: int = 1
    sales_unit_price: float


class SalesInvoiceData(BaseModel):
    """Data for creating a sales invoice."""
    issue_date: str  # YYYY-MM-DD
    due_date: Optional[str] = None
    reference: str
    description: str
    customer: str  # Customer key
    lines: List[SalesInvoiceLine]
    has_line_number: bool = True
    has_line_description: bool = True


class PaymentLine(BaseModel):
    """Line item for payment."""
    account: str  # Account key (UUID)
    line_description: str
    amount: float


class PaymentData(BaseModel):
    """Data for creating a payment."""
    date: str  # YYYY-MM-DD
    paid_from: str  # Bank/cash account key
    payee: str
    description: str
    lines: List[PaymentLine]
    reference: Optional[str] = None
    has_line_description: bool = True


class ReceiptLine(BaseModel):
    """Line item for receipt."""
    account: str  # Account key (UUID)
    line_description: str
    amount: float


class ReceiptData(BaseModel):
    """Data for creating a receipt."""
    date: str  # YYYY-MM-DD
    received_in: str  # Bank/cash account key
    payer: str
    description: str
    lines: List[ReceiptLine]
    reference: Optional[str] = None
    has_line_description: bool = True


class JournalEntryLine(BaseModel):
    """Line item for journal entry."""
    account: str  # Account key (UUID)
    debit: Optional[float] = None
    credit: Optional[float] = None
    line_description: Optional[str] = None


class JournalEntryData(BaseModel):
    """Data for creating a journal entry."""
    date: str  # YYYY-MM-DD
    narration: str  # Description/memo
    lines: List[JournalEntryLine]
    reference: Optional[str] = None


class InterAccountTransferData(BaseModel):
    """Data for creating an inter-account transfer."""
    date: str  # YYYY-MM-DD
    paid_from: str  # Source bank/cash account key
    received_in: str  # Destination bank/cash account key
    amount: float
    description: Optional[str] = None
    reference: Optional[str] = None


class BankReconciliationData(BaseModel):
    """Data for bank reconciliation."""
    bank_account: str  # Bank account key
    statement_date: str  # YYYY-MM-DD
    statement_balance: float
    cleared_transactions: List[str]  # List of transaction keys to mark as cleared


class CreateResponse(BaseModel):
    """Response from creating an entry in Manager.io."""
    success: bool
    key: Optional[str] = None
    message: Optional[str] = None


class UpdateResponse(BaseModel):
    """Response from updating an entry in Manager.io."""
    success: bool
    message: Optional[str] = None


class DeleteResponse(BaseModel):
    """Response from deleting an entry in Manager.io."""
    success: bool
    message: Optional[str] = None


# =============================================================================
# Exceptions
# =============================================================================


class ManagerIOError(Exception):
    """Base exception for Manager.io API errors."""
    pass


class ManagerIOConnectionError(ManagerIOError):
    """Raised when connection to Manager.io fails."""
    pass


class ManagerIOAuthenticationError(ManagerIOError):
    """Raised when authentication fails (401)."""
    pass


class ManagerIOForbiddenError(ManagerIOError):
    """Raised when access is forbidden (403)."""
    pass


class ManagerIONotFoundError(ManagerIOError):
    """Raised when resource is not found (404)."""
    pass


class ManagerIORateLimitError(ManagerIOError):
    """Raised when rate limited (429)."""
    
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


class ManagerIOValidationError(ManagerIOError):
    """Raised when request validation fails (422)."""
    pass


class ManagerIOServerError(ManagerIOError):
    """Raised when server returns 5xx error."""
    pass


# =============================================================================
# Manager.io Client
# =============================================================================


class ManagerIOClient:
    """Client for interacting with Manager.io API.
    
    Provides methods for:
    - Fetching reference data (accounts, suppliers, customers)
    - Fetching paginated transaction data
    - Creating expense claims and purchase invoices
    - Updating existing entries
    
    Features:
    - X-API-KEY authentication
    - Redis caching with configurable TTL
    - Automatic pagination handling
    - Exponential backoff retry logic
    - Comprehensive error handling
    
    Example:
        ```python
        from redis.asyncio import Redis
        
        redis = Redis.from_url("redis://localhost:6379/0")
        client = ManagerIOClient(
            base_url="https://manager.example.com/api2",
            api_key="your-api-key",
            cache=redis,
        )
        
        accounts = await client.get_chart_of_accounts()
        ```
    """
    
    # Default configuration
    DEFAULT_CACHE_TTL = 300  # 5 minutes
    DEFAULT_PAGE_SIZE = 100
    MAX_RETRIES = 3
    INITIAL_RETRY_DELAY = 1.0  # seconds
    MAX_RETRY_DELAY = 30.0  # seconds
    REQUEST_TIMEOUT = 30.0  # seconds
    
    def __init__(
        self,
        base_url: str,
        api_key: str,
        cache: Optional[Redis] = None,
        cache_ttl: Optional[int] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ):
        """Initialize ManagerIOClient.
        
        Args:
            base_url: Manager.io API base URL (e.g., "https://manager.example.com/api2")
            api_key: Manager.io API key for X-API-KEY authentication
            cache: Optional Redis client for caching. If None, caching is disabled.
            cache_ttl: Cache TTL in seconds. Defaults to 300 (5 minutes).
            page_size: Number of records per page for pagination. Defaults to 100.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.cache = cache
        self.cache_ttl = cache_ttl if cache_ttl is not None else self.DEFAULT_CACHE_TTL
        self.page_size = page_size
        
        # HTTP client will be created lazily
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.
        
        Returns:
            Configured httpx.AsyncClient instance
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.REQUEST_TIMEOUT),
                verify=False,  # Allow self-signed certificates
                headers={
                    "X-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def __aenter__(self) -> "ManagerIOClient":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
    
    # =========================================================================
    # Cache Methods
    # =========================================================================
    
    def _get_cache_key(self, endpoint: str, params: Optional[dict] = None) -> str:
        """Generate a cache key for an endpoint and parameters.
        
        Args:
            endpoint: API endpoint path
            params: Optional query parameters
            
        Returns:
            Cache key string
        """
        key_parts = [self.base_url, endpoint]
        if params:
            # Sort params for consistent key generation
            sorted_params = json.dumps(params, sort_keys=True)
            key_parts.append(sorted_params)
        
        key_string = ":".join(key_parts)
        # Use hash for shorter keys
        key_hash = hashlib.md5(key_string.encode()).hexdigest()
        return f"manager_io:{key_hash}"
    
    async def _get_from_cache(self, cache_key: str) -> Optional[Any]:
        """Get data from cache.
        
        Args:
            cache_key: Cache key to retrieve
            
        Returns:
            Cached data or None if not found/expired
        """
        if self.cache is None:
            return None
        
        try:
            cached = await self.cache.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Cache get failed for {cache_key}: {e}")
        
        return None
    
    async def _set_cache(
        self,
        cache_key: str,
        data: Any,
        ttl: Optional[int] = None,
    ) -> None:
        """Store data in cache.
        
        Args:
            cache_key: Cache key to store under
            data: Data to cache (must be JSON serializable)
            ttl: Optional TTL override in seconds
        """
        if self.cache is None:
            return
        
        try:
            ttl = ttl if ttl is not None else self.cache_ttl
            await self.cache.setex(
                cache_key,
                ttl,
                json.dumps(data),
            )
        except Exception as e:
            logger.warning(f"Cache set failed for {cache_key}: {e}")
    
    async def _invalidate_cache(self, pattern: str) -> None:
        """Invalidate cache entries matching a pattern.
        
        Args:
            pattern: Redis key pattern to match (e.g., "manager_io:*")
        """
        if self.cache is None:
            return
        
        try:
            keys = []
            async for key in self.cache.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                await self.cache.delete(*keys)
        except Exception as e:
            logger.warning(f"Cache invalidation failed for {pattern}: {e}")
    
    # =========================================================================
    # HTTP Request Methods
    # =========================================================================
    
    def _handle_response_error(self, response: httpx.Response) -> None:
        """Handle HTTP error responses.
        
        Args:
            response: HTTP response to check
            
        Raises:
            ManagerIOAuthenticationError: For 401 responses
            ManagerIOForbiddenError: For 403 responses
            ManagerIONotFoundError: For 404 responses
            ManagerIOValidationError: For 422 responses
            ManagerIORateLimitError: For 429 responses
            ManagerIOServerError: For 5xx responses
            ManagerIOError: For other error responses
        """
        if response.is_success:
            return
        
        status = response.status_code
        
        try:
            error_detail = response.json()
            message = error_detail.get("detail", response.text)
        except Exception:
            message = response.text or f"HTTP {status}"
        
        if status == 401:
            raise ManagerIOAuthenticationError(
                f"Authentication failed: {message}. Check your API key."
            )
        elif status == 403:
            raise ManagerIOForbiddenError(
                f"Access forbidden: {message}. The API key may lack permissions."
            )
        elif status == 404:
            raise ManagerIONotFoundError(f"Resource not found: {message}")
        elif status == 422:
            raise ManagerIOValidationError(f"Validation error: {message}")
        elif status == 429:
            retry_after = response.headers.get("Retry-After")
            retry_seconds = int(retry_after) if retry_after else None
            raise ManagerIORateLimitError(
                f"Rate limited: {message}",
                retry_after=retry_seconds,
            )
        elif status >= 500:
            raise ManagerIOServerError(f"Server error ({status}): {message}")
        else:
            raise ManagerIOError(f"API error ({status}): {message}")
    
    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        max_retries: Optional[int] = None,
    ) -> httpx.Response:
        """Make an HTTP request with exponential backoff retry.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            params: Optional query parameters
            json_data: Optional JSON body data
            max_retries: Optional max retry count override
            
        Returns:
            HTTP response
            
        Raises:
            ManagerIOError: If all retries fail
        """
        max_retries = max_retries if max_retries is not None else self.MAX_RETRIES
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        client = await self._get_client()
        last_exception: Optional[Exception] = None
        
        for attempt in range(max_retries + 1):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                )
                
                # Handle rate limiting with retry-after
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and attempt < max_retries:
                        delay = min(float(retry_after), self.MAX_RETRY_DELAY)
                        logger.warning(
                            f"Rate limited, waiting {delay}s before retry "
                            f"(attempt {attempt + 1}/{max_retries + 1})"
                        )
                        await asyncio.sleep(delay)
                        continue
                
                # Check for errors
                self._handle_response_error(response)
                return response
                
            except (ManagerIOAuthenticationError, ManagerIOForbiddenError,
                    ManagerIONotFoundError, ManagerIOValidationError):
                # Don't retry client errors
                raise
            except ManagerIORateLimitError as e:
                if attempt < max_retries and e.retry_after:
                    delay = min(e.retry_after, self.MAX_RETRY_DELAY)
                    logger.warning(
                        f"Rate limited, waiting {delay}s before retry "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    await asyncio.sleep(delay)
                    last_exception = e
                    continue
                raise
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last_exception = ManagerIOConnectionError(
                    f"Cannot connect to Manager.io at {self.base_url}: {e}"
                )
                if attempt < max_retries:
                    delay = min(
                        self.INITIAL_RETRY_DELAY * (2 ** attempt),
                        self.MAX_RETRY_DELAY,
                    )
                    logger.warning(
                        f"Connection failed, retrying in {delay}s "
                        f"(attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
            except httpx.TimeoutException as e:
                last_exception = ManagerIOConnectionError(
                    f"Request to Manager.io timed out: {e}"
                )
                if attempt < max_retries:
                    delay = min(
                        self.INITIAL_RETRY_DELAY * (2 ** attempt),
                        self.MAX_RETRY_DELAY,
                    )
                    logger.warning(
                        f"Request timed out, retrying in {delay}s "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    await asyncio.sleep(delay)
                    continue
            except ManagerIOServerError as e:
                last_exception = e
                if attempt < max_retries:
                    delay = min(
                        self.INITIAL_RETRY_DELAY * (2 ** attempt),
                        self.MAX_RETRY_DELAY,
                    )
                    logger.warning(
                        f"Server error, retrying in {delay}s "
                        f"(attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        
        # All retries exhausted
        if last_exception:
            raise last_exception
        raise ManagerIOError("Request failed after all retries")
    
    async def _get(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        use_cache: bool = True,
        cache_ttl: Optional[int] = None,
    ) -> Any:
        """Make a GET request with optional caching.
        
        Args:
            endpoint: API endpoint path
            params: Optional query parameters
            use_cache: Whether to use caching
            cache_ttl: Optional cache TTL override
            
        Returns:
            Response JSON data
        """
        # Check cache first
        if use_cache:
            cache_key = self._get_cache_key(endpoint, params)
            cached = await self._get_from_cache(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit for {endpoint}")
                return cached
        
        # Make request
        response = await self._request_with_retry("GET", endpoint, params=params)
        data = response.json()
        
        # Cache response
        if use_cache:
            await self._set_cache(cache_key, data, ttl=cache_ttl)
        
        return data
    
    async def _post(
        self,
        endpoint: str,
        data: dict,
        params: Optional[dict] = None,
    ) -> Any:
        """Make a POST request.
        
        Args:
            endpoint: API endpoint path
            data: JSON body data
            params: Optional query parameters
            
        Returns:
            Response JSON data
        """
        response = await self._request_with_retry(
            "POST", endpoint, params=params, json_data=data
        )
        return response.json()
    
    async def _put(
        self,
        endpoint: str,
        data: dict,
        params: Optional[dict] = None,
    ) -> Any:
        """Make a PUT request.
        
        Args:
            endpoint: API endpoint path
            data: JSON body data
            params: Optional query parameters
            
        Returns:
            Response JSON data
        """
        response = await self._request_with_retry(
            "PUT", endpoint, params=params, json_data=data
        )
        return response.json()
    
    # =========================================================================
    # Pagination Helper
    # =========================================================================
    
    async def fetch_all_paginated(
        self,
        endpoint: str,
        use_cache: bool = True,
        cache_ttl: Optional[int] = None,
    ) -> List[dict]:
        """Fetch all records from a paginated endpoint.
        
        Automatically handles pagination by making multiple requests
        until all records are retrieved.
        
        Args:
            endpoint: API endpoint path
            use_cache: Whether to cache the complete result
            cache_ttl: Optional cache TTL override
            
        Returns:
            List of all records from the endpoint (normalized with consistent field names)
        """
        # Check cache for complete result
        if use_cache:
            cache_key = self._get_cache_key(f"{endpoint}:all")
            cached = await self._get_from_cache(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit for paginated {endpoint}")
                return cached
        
        all_records: List[dict] = []
        skip = 0
        
        # Map endpoint to expected response key
        endpoint_key_map = {
            "/receipts": "receipts",
            "/payments": "payments",
            "/inter-account-transfers": "interAccountTransfers",
            "/journal-entries": "journalEntries",
            "/expense-claims": "expenseClaims",
            "/purchase-invoices": "purchaseInvoices",
            "/sales-invoices": "salesInvoices",
            "/suppliers": "suppliers",
            "/customers": "customers",
            "/employees": "employees",
            "/tax-codes": "taxCodes",
            "/projects": "projects",
            "/fixed-assets": "fixedAssets",
            "/bank-and-cash-accounts": "bankAndCashAccounts",
            "/chart-of-accounts": "chartOfAccounts",
            "/credit-notes": "creditNotes",
            "/debit-notes": "debitNotes",
            "/inventory-items": "inventoryItems",
            "/production-orders": "productionOrders",
        }
        
        # Get the expected key for this endpoint
        endpoint_clean = endpoint.rstrip("/")
        expected_key = endpoint_key_map.get(endpoint_clean)
        
        while True:
            params = {"skip": skip, "take": self.page_size}
            
            # Don't cache individual pages
            response = await self._request_with_retry("GET", endpoint, params=params)
            data = response.json()
            
            # Handle different response formats
            records = []
            total = None
            
            if isinstance(data, list):
                # Simple list response
                records = data
            elif isinstance(data, dict):
                # Try endpoint-specific key first, then generic keys
                if expected_key and expected_key in data:
                    records = data[expected_key]
                else:
                    records = data.get("items", data.get("data", []))
                
                total = data.get("totalRecords", data.get("total", data.get("count")))
            
            # Normalize records to have consistent field names
            normalized_records = []
            for record in records:
                normalized = self._normalize_record(record)
                normalized_records.append(normalized)
            
            all_records.extend(normalized_records)
            
            # Check if there are more records
            if total is not None:
                if skip + len(records) >= total:
                    break
            elif len(records) < self.page_size:
                break
            
            skip += self.page_size
        
        # Cache complete result
        if use_cache:
            await self._set_cache(cache_key, all_records, ttl=cache_ttl)
        
        return all_records
    
    def _normalize_record(self, record: dict) -> dict:
        """Normalize a record to have consistent field names.
        
        Manager.io API returns nested structures like:
        - amount: {value: 100, currency: "HKD"}
        - receivedIn: {key: "...", name: "..."}
        
        This normalizes them to flat structures while keeping both
        original and normalized field names for compatibility.
        """
        normalized = {}
        
        for key, value in record.items():
            # Handle nested amount/balance structures
            if key in ("amount", "actualBalance") and isinstance(value, dict):
                normalized["Amount"] = float(value.get("value", 0))
                normalized["amount"] = normalized["Amount"]  # Keep lowercase too
                normalized["Currency"] = value.get("currency", "USD")
            # Handle nested account references
            elif key in ("receivedIn", "paidFrom", "bankAccount", "account") and isinstance(value, dict):
                # Map to standard field names
                field_map = {
                    "receivedIn": "BankAccount",
                    "paidFrom": "BankAccount", 
                    "bankAccount": "BankAccount",
                    "account": "Account",
                }
                account_key = value.get("key", "")
                normalized[field_map.get(key, "Account")] = account_key
                normalized[f"{field_map.get(key, 'Account')}Name"] = value.get("name", "")
                # Also keep original nested structure for compatibility
                normalized[key] = value
            # Handle nested supplier/customer references
            elif key in ("supplier", "customer", "paidBy") and isinstance(value, dict):
                normalized[key.capitalize()] = value.get("key", "")
                normalized[f"{key.capitalize()}Name"] = value.get("name", "")
                normalized[key] = value  # Keep original
            # Handle date fields
            elif key == "date":
                normalized["Date"] = value
                normalized["date"] = value  # Keep lowercase too
            # Handle reference fields
            elif key == "reference":
                normalized["Reference"] = value
                normalized["reference"] = value
            # Handle description fields
            elif key == "description":
                normalized["Description"] = value
                normalized["description"] = value
            # Handle key field
            elif key == "key":
                normalized["Key"] = value
                normalized["key"] = value  # Keep lowercase too
            # Handle name field
            elif key == "name":
                normalized["Name"] = value
                normalized["name"] = value  # Keep lowercase too
            # Keep other fields as-is
            else:
                normalized[key] = value
                # Also add capitalized version
                if key[0].islower():
                    normalized[key.capitalize()] = value
        
        # Keep raw record for debugging
        normalized["_raw"] = record
        
        return normalized
    
    # =========================================================================
    # Data Fetching Methods
    # =========================================================================
    
    async def get_chart_of_accounts(self) -> List[Account]:
        """Fetch chart of accounts from Manager.io.
        
        Uses caching to reduce API calls. The chart of accounts is reference
        data that changes infrequently.
        
        Returns:
            List of Account objects
            
        Raises:
            ManagerIOError: If the request fails
        """
        endpoint = "/chart-of-accounts"
        
        # Use caching for reference data
        data = await self._get(endpoint, use_cache=True)
        
        # Parse response - handle Manager.io format with 'chartOfAccounts' key
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get("chartOfAccounts", 
                      data.get("items", 
                      data.get("data", [])))
        else:
            records = []
        
        # Convert to Account models
        accounts = []
        for record in records:
            try:
                # Handle different field name formats from API
                account = Account(
                    key=record.get("Key", record.get("key", "")),
                    name=record.get("Name", record.get("name", "")),
                    code=record.get("Code", record.get("code")),
                )
                accounts.append(account)
            except Exception as e:
                logger.warning(f"Failed to parse account record: {e}")
                continue
        
        return accounts
    
    async def get_suppliers(self) -> List[Supplier]:
        """Fetch suppliers from Manager.io.
        
        Uses caching to reduce API calls.
        
        Returns:
            List of Supplier objects
            
        Raises:
            ManagerIOError: If the request fails
        """
        endpoint = "/suppliers"
        
        # Check cache first
        cache_key = self._get_cache_key(endpoint)
        cached = await self._get_from_cache(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for {endpoint}")
            return [
                Supplier(
                    key=record.get("Key", record.get("key", "")),
                    name=record.get("Name", record.get("name", "")),
                )
                for record in cached
            ]
        
        # Use GET for suppliers endpoint
        data = await self._get(endpoint, use_cache=False)
        
        # Parse response - Manager.io returns data under 'suppliers' key
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get("suppliers", 
                      data.get("items", 
                      data.get("data", [])))
        else:
            records = []
        
        # Cache the raw records
        await self._set_cache(cache_key, records)
        
        # Convert to Supplier models
        suppliers = []
        for record in records:
            try:
                supplier = Supplier(
                    key=record.get("Key", record.get("key", "")),
                    name=record.get("Name", record.get("name", "")),
                )
                suppliers.append(supplier)
            except Exception as e:
                logger.warning(f"Failed to parse supplier record: {e}")
                continue
        
        return suppliers
    
    async def get_customers(self) -> List[Customer]:
        """Fetch customers from Manager.io.
        
        Uses caching to reduce API calls. Customers are reference data
        that changes infrequently.
        
        Returns:
            List of Customer objects
            
        Raises:
            ManagerIOError: If the request fails
        """
        endpoint = "/customers"
        
        # Use caching for reference data
        data = await self._get(endpoint, use_cache=True)
        
        # Parse response - Manager.io returns data under 'customers' key
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get("customers", 
                      data.get("items", 
                      data.get("data", [])))
        else:
            records = []
        
        # Convert to Customer models
        customers = []
        for record in records:
            try:
                customer = Customer(
                    key=record.get("Key", record.get("key", "")),
                    name=record.get("Name", record.get("name", "")),
                )
                customers.append(customer)
            except Exception as e:
                logger.warning(f"Failed to parse customer record: {e}")
                continue
        
        return customers
    
    async def _get_paginated(
        self,
        endpoint: str,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Helper method to fetch paginated data from an endpoint.
        
        Args:
            endpoint: API endpoint path
            skip: Number of records to skip
            take: Number of records to return (maps to pageSize in API)
            
        Returns:
            PaginatedResponse with records
            
        Raises:
            ManagerIOError: If the request fails
        """
        # Manager.io API uses 'pageSize' not 'take'
        params = {"skip": skip, "pageSize": take}
        
        # Map endpoint to expected response key
        endpoint_key_map = {
            "/receipts": "receipts",
            "/payments": "payments",
            "/inter-account-transfers": "interAccountTransfers",
            "/journal-entries": "journalEntries",
            "/expense-claims": "expenseClaims",
            "/purchase-invoices": "purchaseInvoices",
            "/sales-invoices": "salesInvoices",
            "/suppliers": "suppliers",
            "/customers": "customers",
            "/employees": "employees",
            "/tax-codes": "taxCodes",
            "/projects": "projects",
            "/fixed-assets": "fixedAssets",
            "/bank-and-cash-accounts": "bankAndCashAccounts",
            "/chart-of-accounts": "chartOfAccounts",
            "/credit-notes": "creditNotes",
            "/debit-notes": "debitNotes",
            "/inventory-items": "inventoryItems",
            "/inventory-kits": "inventoryKits",
            "/goods-receipts": "goodsReceipts",
            "/delivery-notes": "deliveryNotes",
            "/sales-orders": "salesOrders",
            "/purchase-orders": "purchaseOrders",
            "/investments": "investments",
            "/investment-transactions": "investmentTransactions",
        }
        
        # Get the expected key for this endpoint
        endpoint_clean = endpoint.rstrip("/")
        expected_key = endpoint_key_map.get(endpoint_clean)
        
        # Don't cache paginated requests (they change frequently)
        data = await self._get(endpoint, params=params, use_cache=False)
        
        # Parse response - Manager.io returns data in endpoint-specific keys
        items = []
        total = 0
        
        if isinstance(data, list):
            items = data
            total = len(items) + skip  # Estimate total if not provided
        elif isinstance(data, dict):
            # Try endpoint-specific key first (e.g., "receipts", "payments")
            if expected_key and expected_key in data:
                items = data[expected_key]
            else:
                # Fallback to generic keys
                items = data.get("items", data.get("data", []))
            
            # Get total from response
            total = data.get("totalRecords", data.get("total", data.get("count", len(items) + skip)))
        
        return PaginatedResponse(
            items=items,
            total=total,
            skip=skip,
            take=take,
        )
    
    async def get_payments(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch payments from Manager.io.
        
        Args:
            skip: Number of records to skip
            take: Number of records to return
            
        Returns:
            PaginatedResponse with payment records
            
        Raises:
            ManagerIOError: If the request fails
        """
        return await self._get_paginated("/payments", skip=skip, take=take)
    
    async def get_receipts(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch receipts from Manager.io.
        
        Args:
            skip: Number of records to skip
            take: Number of records to return
            
        Returns:
            PaginatedResponse with receipt records
            
        Raises:
            ManagerIOError: If the request fails
        """
        return await self._get_paginated("/receipts", skip=skip, take=take)
    
    async def get_expense_claims(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch expense claims from Manager.io.
        
        Args:
            skip: Number of records to skip
            take: Number of records to return
            
        Returns:
            PaginatedResponse with expense claim records
            
        Raises:
            ManagerIOError: If the request fails
        """
        return await self._get_paginated("/expense-claims", skip=skip, take=take)
    
    async def get_transfers(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch inter-account transfers from Manager.io.
        
        Args:
            skip: Number of records to skip
            take: Number of records to return
            
        Returns:
            PaginatedResponse with transfer records
            
        Raises:
            ManagerIOError: If the request fails
        """
        return await self._get_paginated("/inter-account-transfers", skip=skip, take=take)
    
    async def get_journal_entries(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch journal entries from Manager.io.
        
        Args:
            skip: Number of records to skip
            take: Number of records to return
            
        Returns:
            PaginatedResponse with journal entry records
            
        Raises:
            ManagerIOError: If the request fails
        """
        return await self._get_paginated("/journal-entries", skip=skip, take=take)
    
    async def get_general_ledger(self, view_id: str) -> dict:
        """Fetch general ledger data from Manager.io.
        
        Args:
            view_id: General ledger view ID
            
        Returns:
            General ledger data as a dictionary
            
        Raises:
            ManagerIOError: If the request fails
            ManagerIONotFoundError: If the view ID is not found
        """
        endpoint = f"/general-ledger-transactions-view/{view_id}"
        
        # Don't cache general ledger views (they contain transaction data)
        data = await self._get(endpoint, use_cache=False)
        
        return data
    
    # =========================================================================
    # Entry Submission Methods
    # =========================================================================
    
    def _validate_expense_claim_data(self, data: ExpenseClaimData) -> None:
        """Validate expense claim data before submission.
        
        Args:
            data: Expense claim data to validate
            
        Raises:
            ManagerIOValidationError: If validation fails
        """
        errors = []
        
        # Validate required fields
        if not data.date:
            errors.append("Date is required")
        if not data.paid_by:
            errors.append("PaidBy (employee) is required")
        if not data.payee:
            errors.append("Payee is required")
        if not data.description:
            errors.append("Description is required")
        if not data.lines or len(data.lines) == 0:
            errors.append("At least one line item is required")
        
        # Validate line items
        for i, line in enumerate(data.lines):
            if not line.account:
                errors.append(f"Line {i + 1}: Account is required")
            if not line.line_description:
                errors.append(f"Line {i + 1}: Line description is required")
            if line.qty <= 0:
                errors.append(f"Line {i + 1}: Quantity must be positive")
            if line.purchase_unit_price < 0:
                errors.append(f"Line {i + 1}: Unit price cannot be negative")
        
        if errors:
            raise ManagerIOValidationError(
                f"Expense claim validation failed: {'; '.join(errors)}"
            )
    
    def _validate_purchase_invoice_data(self, data: PurchaseInvoiceData) -> None:
        """Validate purchase invoice data before submission.
        
        Args:
            data: Purchase invoice data to validate
            
        Raises:
            ManagerIOValidationError: If validation fails
        """
        errors = []
        
        # Validate required fields
        if not data.issue_date:
            errors.append("IssueDate is required")
        if not data.reference:
            errors.append("Reference is required")
        if not data.description:
            errors.append("Description is required")
        if not data.supplier:
            errors.append("Supplier is required")
        if not data.lines or len(data.lines) == 0:
            errors.append("At least one line item is required")
        
        # Validate line items
        for i, line in enumerate(data.lines):
            if not line.account:
                errors.append(f"Line {i + 1}: Account is required")
            if not line.line_description:
                errors.append(f"Line {i + 1}: Line description is required")
            if line.purchase_unit_price < 0:
                errors.append(f"Line {i + 1}: Unit price cannot be negative")
        
        if errors:
            raise ManagerIOValidationError(
                f"Purchase invoice validation failed: {'; '.join(errors)}"
            )
    
    def _build_expense_claim_payload(self, data: ExpenseClaimData) -> dict:
        """Build Manager.io API payload for expense claim.
        
        Converts ExpenseClaimData to the Manager.io API payload format.
        
        Args:
            data: Expense claim data
            
        Returns:
            Dictionary payload for Manager.io API
        """
        # Build custom fields structure (empty by default)
        custom_fields2 = {
            "Strings": {},
            "Decimals": {},
            "Dates": {},
            "Booleans": {},
            "StringArrays": {},
        }
        
        # Build line items
        lines = []
        for line in data.lines:
            line_payload = {
                "Account": line.account,
                "LineDescription": line.line_description,
                "CustomFields": {},
                "CustomFields2": custom_fields2.copy(),
                "Qty": line.qty,
                "PurchaseUnitPrice": line.purchase_unit_price,
            }
            lines.append(line_payload)
        
        # Build main payload
        payload = {
            "Date": data.date,
            "PaidBy": data.paid_by,
            "Payee": data.payee,
            "Description": data.description,
            "Lines": lines,
            "HasLineDescription": data.has_line_description,
            "ExpenseClaimFooters": [],
            "CustomFields": {},
            "CustomFields2": custom_fields2.copy(),
        }
        
        return payload
    
    def _build_purchase_invoice_payload(self, data: PurchaseInvoiceData) -> dict:
        """Build Manager.io API payload for purchase invoice.
        
        Converts PurchaseInvoiceData to the Manager.io API payload format.
        
        Args:
            data: Purchase invoice data
            
        Returns:
            Dictionary payload for Manager.io API
        """
        # Build custom fields structure (empty by default)
        custom_fields2 = {
            "Strings": {},
            "Decimals": {},
            "Dates": {},
            "Booleans": {},
            "StringArrays": {},
        }
        
        # Build line items
        lines = []
        for line in data.lines:
            line_payload = {
                "Account": line.account,
                "LineDescription": line.line_description,
                "CustomFields": {},
                "CustomFields2": custom_fields2.copy(),
                "PurchaseUnitPrice": line.purchase_unit_price,
            }
            lines.append(line_payload)
        
        # Build main payload
        payload = {
            "IssueDate": data.issue_date,
            "Reference": data.reference,
            "Description": data.description,
            "Supplier": data.supplier,
            "Lines": lines,
            "HasLineNumber": data.has_line_number,
            "HasLineDescription": data.has_line_description,
        }
        
        return payload
    
    async def create_expense_claim(self, data: ExpenseClaimData) -> CreateResponse:
        """Create an expense claim in Manager.io.
        
        Validates the expense claim data, converts it to the Manager.io API
        payload format, and POSTs to the /expense-claim-form endpoint.
        
        Args:
            data: Expense claim data containing date, paid_by, payee,
                  description, and line items
            
        Returns:
            CreateResponse with success status and entry key
            
        Raises:
            ManagerIOValidationError: If data validation fails
            ManagerIOError: If the API request fails
            
        Example:
            ```python
            data = ExpenseClaimData(
                date="2024-01-15",
                paid_by="employee-uuid",
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
            response = await client.create_expense_claim(data)
            print(f"Created expense claim: {response.key}")
            ```
        """
        # Validate data before submission
        self._validate_expense_claim_data(data)
        
        # Build API payload
        payload = self._build_expense_claim_payload(data)
        
        # POST to expense-claim-form endpoint
        endpoint = "/expense-claim-form"
        
        try:
            response_data = await self._post(endpoint, payload)
            
            # Parse response - Manager.io returns the created entry key
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                # Some APIs return just the key as a string
                entry_key = response_data
            
            return CreateResponse(
                success=True,
                key=entry_key,
                message="Expense claim created successfully",
            )
            
        except ManagerIOValidationError:
            # Re-raise validation errors
            raise
        except ManagerIOError as e:
            # Return failure response for other errors
            return CreateResponse(
                success=False,
                key=None,
                message=str(e),
            )
    
    async def create_purchase_invoice(
        self,
        data: PurchaseInvoiceData,
    ) -> CreateResponse:
        """Create a purchase invoice in Manager.io.
        
        Validates the purchase invoice data, converts it to the Manager.io API
        payload format, and POSTs to the /purchase-invoice-form endpoint.
        
        Args:
            data: Purchase invoice data containing issue_date, reference,
                  description, supplier, and line items
            
        Returns:
            CreateResponse with success status and entry key
            
        Raises:
            ManagerIOValidationError: If data validation fails
            ManagerIOError: If the API request fails
            
        Example:
            ```python
            data = PurchaseInvoiceData(
                issue_date="2024-01-15",
                reference="#INV-001",
                description="Office supplies",
                supplier="supplier-uuid",
                lines=[
                    PurchaseInvoiceLine(
                        account="expense-account-uuid",
                        line_description="Printer paper and ink",
                        purchase_unit_price=89.99,
                    )
                ],
            )
            response = await client.create_purchase_invoice(data)
            print(f"Created purchase invoice: {response.key}")
            ```
        """
        # Validate data before submission
        self._validate_purchase_invoice_data(data)
        
        # Build API payload
        payload = self._build_purchase_invoice_payload(data)
        
        # POST to purchase-invoice-form endpoint
        endpoint = "/purchase-invoice-form"
        
        try:
            response_data = await self._post(endpoint, payload)
            
            # Parse response - Manager.io returns the created entry key
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                # Some APIs return just the key as a string
                entry_key = response_data
            
            return CreateResponse(
                success=True,
                key=entry_key,
                message="Purchase invoice created successfully",
            )
            
        except ManagerIOValidationError:
            # Re-raise validation errors
            raise
        except ManagerIOError as e:
            # Return failure response for other errors
            return CreateResponse(
                success=False,
                key=None,
                message=str(e),
            )
    
    async def update_entry(
        self,
        entry_type: str,
        entry_id: str,
        data: dict,
    ) -> UpdateResponse:
        """Update an existing entry in Manager.io.
        
        Updates an entry by its type and ID. The data dictionary should contain
        the fields to update in Manager.io API format.
        
        Args:
            entry_type: Type of entry (e.g., "expense-claim-form", "purchase-invoice-form")
            entry_id: Entry UUID
            data: Updated entry data in Manager.io API format
            
        Returns:
            UpdateResponse with success status
            
        Raises:
            ManagerIOValidationError: If entry_type or entry_id is invalid
            ManagerIONotFoundError: If the entry is not found
            ManagerIOError: If the API request fails
            
        Example:
            ```python
            response = await client.update_entry(
                entry_type="expense-claim-form",
                entry_id="entry-uuid",
                data={"Description": "Updated description"},
            )
            if response.success:
                print("Entry updated successfully")
            ```
        """
        # Validate inputs
        if not entry_type:
            raise ManagerIOValidationError("Entry type is required")
        if not entry_id:
            raise ManagerIOValidationError("Entry ID is required")
        if not data:
            raise ManagerIOValidationError("Update data is required")
        
        # Build endpoint - Manager.io uses /{entry-type}/{entry-id} for updates
        endpoint = f"/{entry_type.lstrip('/')}/{entry_id}"
        
        try:
            await self._put(endpoint, data)
            
            return UpdateResponse(
                success=True,
                message="Entry updated successfully",
            )
            
        except ManagerIONotFoundError:
            # Re-raise not found errors
            raise
        except ManagerIOValidationError:
            # Re-raise validation errors
            raise
        except ManagerIOError as e:
            # Return failure response for other errors
            return UpdateResponse(
                success=False,
                message=str(e),
            )

    # =========================================================================
    # Sales Invoice Methods
    # =========================================================================
    
    def _validate_sales_invoice_data(self, data: SalesInvoiceData) -> None:
        """Validate sales invoice data before submission."""
        errors = []
        
        if not data.issue_date:
            errors.append("IssueDate is required")
        if not data.reference:
            errors.append("Reference is required")
        if not data.customer:
            errors.append("Customer is required")
        if not data.lines or len(data.lines) == 0:
            errors.append("At least one line item is required")
        
        for i, line in enumerate(data.lines):
            if not line.account:
                errors.append(f"Line {i + 1}: Account is required")
            if line.qty <= 0:
                errors.append(f"Line {i + 1}: Quantity must be positive")
            if line.sales_unit_price < 0:
                errors.append(f"Line {i + 1}: Unit price cannot be negative")
        
        if errors:
            raise ManagerIOValidationError(
                f"Sales invoice validation failed: {'; '.join(errors)}"
            )
    
    def _build_sales_invoice_payload(self, data: SalesInvoiceData) -> dict:
        """Build Manager.io API payload for sales invoice."""
        custom_fields2 = {
            "Strings": {},
            "Decimals": {},
            "Dates": {},
            "Booleans": {},
            "StringArrays": {},
        }
        
        lines = []
        for line in data.lines:
            line_payload = {
                "Account": line.account,
                "LineDescription": line.line_description,
                "CustomFields": {},
                "CustomFields2": custom_fields2.copy(),
                "Qty": line.qty,
                "SalesUnitPrice": line.sales_unit_price,
            }
            lines.append(line_payload)
        
        payload = {
            "IssueDate": data.issue_date,
            "Reference": data.reference,
            "Description": data.description,
            "Customer": data.customer,
            "Lines": lines,
            "HasLineNumber": data.has_line_number,
            "HasLineDescription": data.has_line_description,
        }
        
        if data.due_date:
            payload["DueDate"] = data.due_date
        
        return payload
    
    async def create_sales_invoice(self, data: SalesInvoiceData) -> CreateResponse:
        """Create a sales invoice in Manager.io.
        
        Args:
            data: Sales invoice data
            
        Returns:
            CreateResponse with success status and entry key
        """
        self._validate_sales_invoice_data(data)
        payload = self._build_sales_invoice_payload(data)
        endpoint = "/sales-invoice-form"
        
        try:
            response_data = await self._post(endpoint, payload)
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                entry_key = response_data
            
            return CreateResponse(
                success=True,
                key=entry_key,
                message="Sales invoice created successfully",
            )
        except ManagerIOValidationError:
            raise
        except ManagerIOError as e:
            return CreateResponse(success=False, key=None, message=str(e))
    
    # =========================================================================
    # Payment Methods
    # =========================================================================
    
    def _validate_payment_data(self, data: PaymentData) -> None:
        """Validate payment data before submission."""
        errors = []
        
        if not data.date:
            errors.append("Date is required")
        if not data.paid_from:
            errors.append("PaidFrom (bank/cash account) is required")
        if not data.payee:
            errors.append("Payee is required")
        if not data.lines or len(data.lines) == 0:
            errors.append("At least one line item is required")
        
        for i, line in enumerate(data.lines):
            if not line.account:
                errors.append(f"Line {i + 1}: Account is required")
            if line.amount < 0:
                errors.append(f"Line {i + 1}: Amount cannot be negative")
        
        if errors:
            raise ManagerIOValidationError(
                f"Payment validation failed: {'; '.join(errors)}"
            )
    
    def _build_payment_payload(self, data: PaymentData) -> dict:
        """Build Manager.io API payload for payment."""
        custom_fields2 = {
            "Strings": {},
            "Decimals": {},
            "Dates": {},
            "Booleans": {},
            "StringArrays": {},
        }
        
        lines = []
        for line in data.lines:
            line_payload = {
                "Account": line.account,
                "LineDescription": line.line_description,
                "CustomFields": {},
                "CustomFields2": custom_fields2.copy(),
                "Amount": line.amount,
            }
            lines.append(line_payload)
        
        payload = {
            "Date": data.date,
            "PaidFrom": data.paid_from,
            "Payee": data.payee,
            "Description": data.description,
            "Lines": lines,
            "HasLineDescription": data.has_line_description,
        }
        
        if data.reference:
            payload["Reference"] = data.reference
        
        return payload
    
    async def create_payment(self, data: PaymentData) -> CreateResponse:
        """Create a payment in Manager.io.
        
        Args:
            data: Payment data
            
        Returns:
            CreateResponse with success status and entry key
        """
        self._validate_payment_data(data)
        payload = self._build_payment_payload(data)
        endpoint = "/payment-form"
        
        try:
            response_data = await self._post(endpoint, payload)
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                entry_key = response_data
            
            return CreateResponse(
                success=True,
                key=entry_key,
                message="Payment created successfully",
            )
        except ManagerIOValidationError:
            raise
        except ManagerIOError as e:
            return CreateResponse(success=False, key=None, message=str(e))
    
    # =========================================================================
    # Receipt Methods
    # =========================================================================
    
    def _validate_receipt_data(self, data: ReceiptData) -> None:
        """Validate receipt data before submission."""
        errors = []
        
        if not data.date:
            errors.append("Date is required")
        if not data.received_in:
            errors.append("ReceivedIn (bank/cash account) is required")
        if not data.payer:
            errors.append("Payer is required")
        if not data.lines or len(data.lines) == 0:
            errors.append("At least one line item is required")
        
        for i, line in enumerate(data.lines):
            if not line.account:
                errors.append(f"Line {i + 1}: Account is required")
            if line.amount < 0:
                errors.append(f"Line {i + 1}: Amount cannot be negative")
        
        if errors:
            raise ManagerIOValidationError(
                f"Receipt validation failed: {'; '.join(errors)}"
            )
    
    def _build_receipt_payload(self, data: ReceiptData) -> dict:
        """Build Manager.io API payload for receipt."""
        custom_fields2 = {
            "Strings": {},
            "Decimals": {},
            "Dates": {},
            "Booleans": {},
            "StringArrays": {},
        }
        
        lines = []
        for line in data.lines:
            line_payload = {
                "Account": line.account,
                "LineDescription": line.line_description,
                "CustomFields": {},
                "CustomFields2": custom_fields2.copy(),
                "Amount": line.amount,
            }
            lines.append(line_payload)
        
        payload = {
            "Date": data.date,
            "ReceivedIn": data.received_in,
            "Payer": data.payer,
            "Description": data.description,
            "Lines": lines,
            "HasLineDescription": data.has_line_description,
        }
        
        if data.reference:
            payload["Reference"] = data.reference
        
        return payload
    
    async def create_receipt(self, data: ReceiptData) -> CreateResponse:
        """Create a receipt in Manager.io.
        
        Args:
            data: Receipt data
            
        Returns:
            CreateResponse with success status and entry key
        """
        self._validate_receipt_data(data)
        payload = self._build_receipt_payload(data)
        endpoint = "/receipt-form"
        
        try:
            response_data = await self._post(endpoint, payload)
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                entry_key = response_data
            
            return CreateResponse(
                success=True,
                key=entry_key,
                message="Receipt created successfully",
            )
        except ManagerIOValidationError:
            raise
        except ManagerIOError as e:
            return CreateResponse(success=False, key=None, message=str(e))
    
    # =========================================================================
    # Journal Entry Methods
    # =========================================================================
    
    def _validate_journal_entry_data(self, data: JournalEntryData) -> None:
        """Validate journal entry data before submission."""
        errors = []
        
        if not data.date:
            errors.append("Date is required")
        if not data.narration:
            errors.append("Narration is required")
        if not data.lines or len(data.lines) < 2:
            errors.append("At least two line items are required for a journal entry")
        
        total_debit = 0.0
        total_credit = 0.0
        
        for i, line in enumerate(data.lines):
            if not line.account:
                errors.append(f"Line {i + 1}: Account is required")
            if line.debit is None and line.credit is None:
                errors.append(f"Line {i + 1}: Either debit or credit is required")
            if line.debit is not None and line.credit is not None:
                errors.append(f"Line {i + 1}: Cannot have both debit and credit")
            if line.debit is not None:
                if line.debit < 0:
                    errors.append(f"Line {i + 1}: Debit cannot be negative")
                total_debit += line.debit
            if line.credit is not None:
                if line.credit < 0:
                    errors.append(f"Line {i + 1}: Credit cannot be negative")
                total_credit += line.credit
        
        # Check that debits equal credits
        if abs(total_debit - total_credit) > 0.01:
            errors.append(f"Debits ({total_debit:.2f}) must equal credits ({total_credit:.2f})")
        
        if errors:
            raise ManagerIOValidationError(
                f"Journal entry validation failed: {'; '.join(errors)}"
            )
    
    def _build_journal_entry_payload(self, data: JournalEntryData) -> dict:
        """Build Manager.io API payload for journal entry."""
        custom_fields2 = {
            "Strings": {},
            "Decimals": {},
            "Dates": {},
            "Booleans": {},
            "StringArrays": {},
        }
        
        lines = []
        for line in data.lines:
            line_payload = {
                "Account": line.account,
                "CustomFields": {},
                "CustomFields2": custom_fields2.copy(),
            }
            if line.debit is not None:
                line_payload["Debit"] = line.debit
            if line.credit is not None:
                line_payload["Credit"] = line.credit
            if line.line_description:
                line_payload["LineDescription"] = line.line_description
            lines.append(line_payload)
        
        payload = {
            "Date": data.date,
            "Narration": data.narration,
            "Lines": lines,
        }
        
        if data.reference:
            payload["Reference"] = data.reference
        
        return payload
    
    async def create_journal_entry(self, data: JournalEntryData) -> CreateResponse:
        """Create a journal entry in Manager.io.
        
        Args:
            data: Journal entry data
            
        Returns:
            CreateResponse with success status and entry key
        """
        self._validate_journal_entry_data(data)
        payload = self._build_journal_entry_payload(data)
        endpoint = "/journal-entry-form"
        
        try:
            response_data = await self._post(endpoint, payload)
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                entry_key = response_data
            
            return CreateResponse(
                success=True,
                key=entry_key,
                message="Journal entry created successfully",
            )
        except ManagerIOValidationError:
            raise
        except ManagerIOError as e:
            return CreateResponse(success=False, key=None, message=str(e))
    
    # =========================================================================
    # Inter-Account Transfer Methods
    # =========================================================================
    
    def _validate_transfer_data(self, data: InterAccountTransferData) -> None:
        """Validate inter-account transfer data before submission."""
        errors = []
        
        if not data.date:
            errors.append("Date is required")
        if not data.paid_from:
            errors.append("PaidFrom (source account) is required")
        if not data.received_in:
            errors.append("ReceivedIn (destination account) is required")
        if data.paid_from == data.received_in:
            errors.append("Source and destination accounts must be different")
        if data.amount <= 0:
            errors.append("Amount must be positive")
        
        if errors:
            raise ManagerIOValidationError(
                f"Transfer validation failed: {'; '.join(errors)}"
            )
    
    def _build_transfer_payload(self, data: InterAccountTransferData) -> dict:
        """Build Manager.io API payload for inter-account transfer."""
        payload = {
            "Date": data.date,
            "PaidFrom": data.paid_from,
            "ReceivedIn": data.received_in,
            "Amount": data.amount,
        }
        
        if data.description:
            payload["Description"] = data.description
        if data.reference:
            payload["Reference"] = data.reference
        
        return payload
    
    async def create_transfer(self, data: InterAccountTransferData) -> CreateResponse:
        """Create an inter-account transfer in Manager.io.
        
        Args:
            data: Transfer data
            
        Returns:
            CreateResponse with success status and entry key
        """
        self._validate_transfer_data(data)
        payload = self._build_transfer_payload(data)
        endpoint = "/inter-account-transfer-form"
        
        try:
            response_data = await self._post(endpoint, payload)
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                entry_key = response_data
            
            return CreateResponse(
                success=True,
                key=entry_key,
                message="Transfer created successfully",
            )
        except ManagerIOValidationError:
            raise
        except ManagerIOError as e:
            return CreateResponse(success=False, key=None, message=str(e))
    
    # =========================================================================
    # Report Methods (using Manager.io form-based report API)
    # =========================================================================
    
    async def _get_report_view(
        self,
        form_endpoint: str,
        view_endpoint: str,
        form_data: Optional[dict] = None,
    ) -> dict:
        """Generic method to fetch a report using form/view pattern.
        
        Manager.io reports require:
        1. POST to form endpoint to create report config, returns Key
        2. GET from view endpoint with that Key to get report data
        
        Args:
            form_endpoint: e.g., "/profit-and-loss-statement-form"
            view_endpoint: e.g., "/profit-and-loss-statement-view"
            form_data: Optional data to POST to form endpoint
            
        Returns:
            Report data as dictionary
        """
        try:
            client = await self._get_client()
            
            # Step 1: Create report form to get Key
            form_response = await client.post(
                f"{self.base_url}{form_endpoint}",
                json=form_data or {},
            )
            self._handle_response_error(form_response)
            form_result = form_response.json()
            
            # Get the key from response (could be "Key" or "key")
            report_key = form_result.get("Key") or form_result.get("key")
            if not report_key:
                logger.warning(f"No key in form response: {form_result}")
                return {"error": "No report key returned", "form_response": form_result}
            
            # Step 2: Fetch report view using the key
            view_response = await client.get(
                f"{self.base_url}{view_endpoint}/{report_key}",
            )
            self._handle_response_error(view_response)
            return view_response.json()
            
        except Exception as e:
            logger.error(f"Report fetch error: {e}")
            return {"error": str(e)}
    
    async def get_balance_sheet(self, as_of_date: Optional[str] = None) -> dict:
        """Fetch balance sheet report from Manager.io.
        
        Args:
            as_of_date: Optional date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Balance sheet data as a dictionary with Columns and Rows
            
        Note:
            Falls back to derived report from GL Summary if native endpoint fails.
        """
        form_data = {}
        if as_of_date:
            form_data["Date"] = as_of_date
        
        # Try native endpoint first
        result = await self._get_report_view(
            "/balance-sheet-form",
            "/balance-sheet-view",
            form_data,
        )
        
        # If native fails, use derived version
        if "error" in result:
            logger.info("Native balance sheet failed, using derived version")
            return await self.get_balance_sheet_derived(as_of_date)
        
        return result
    
    async def get_profit_and_loss(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> dict:
        """Fetch profit and loss (income statement) report from Manager.io.
        
        Args:
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            
        Returns:
            P&L data with Columns and Rows showing income/expenses
            
        Note:
            Falls back to derived report from GL Summary if native endpoint fails.
        """
        form_data = {}
        if from_date:
            form_data["FromDate"] = from_date
        if to_date:
            form_data["ToDate"] = to_date
        
        # Try native endpoint first
        result = await self._get_report_view(
            "/profit-and-loss-statement-form",
            "/profit-and-loss-statement-view",
            form_data,
        )
        
        # If native fails, use derived version
        if "error" in result:
            logger.info("Native P&L failed, using derived version")
            return await self.get_profit_and_loss_derived(from_date, to_date)
        
        return result
    
    async def get_cash_flow_statement(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> dict:
        """Fetch cash flow statement from Manager.io.
        
        Args:
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            
        Returns:
            Cash flow statement data
            
        Note:
            Falls back to derived report from bank transactions if native endpoint fails.
        """
        form_data = {}
        if from_date:
            form_data["FromDate"] = from_date
        if to_date:
            form_data["ToDate"] = to_date
        
        # Try native endpoint first
        result = await self._get_report_view(
            "/cash-flow-statement-form",
            "/cash-flow-statement-view",
            form_data,
        )
        
        # If native fails, use derived version
        if "error" in result:
            logger.info("Native cash flow failed, using derived version")
            return await self.get_cash_flow_derived(from_date, to_date)
        
        return result
    
    async def get_cash_flow_derived(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> dict:
        """Generate Cash Flow Statement from receipts and payments.
        
        This is a simplified cash flow derived from actual cash movements.
        It categorizes cash flows into operating, investing, and financing
        based on the accounts involved.
        
        Args:
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            
        Returns:
            Cash flow statement with operating, investing, financing sections
        """
        try:
            # Get receipts and payments for the period
            # Note: We fetch all and filter by date since API may not support date filtering
            receipts_resp = await self._get_paginated("/receipts", skip=0, take=500)
            payments_resp = await self._get_paginated("/payments", skip=0, take=500)
            
            # Get bank account balances
            bank_accounts = await self.get_bank_accounts()
            
            # Filter by date if provided
            def in_date_range(item: dict) -> bool:
                item_date = item.get("date", "")
                if from_date and item_date < from_date:
                    return False
                if to_date and item_date > to_date:
                    return False
                return True
            
            receipts = [r for r in receipts_resp.items if in_date_range(r)]
            payments = [p for p in payments_resp.items if in_date_range(p)]
            
            # Calculate totals
            def get_amount(item: dict) -> float:
                amt = item.get("amount", {})
                if isinstance(amt, dict):
                    return float(amt.get("value", 0) or 0)
                return float(amt or 0)
            
            total_receipts = sum(get_amount(r) for r in receipts)
            total_payments = sum(get_amount(p) for p in payments)
            net_cash_flow = total_receipts - total_payments
            
            # Categorize (simplified - all as operating for now)
            # A proper implementation would analyze account types
            operating = {
                "receipts": total_receipts,
                "payments": total_payments,
                "net": net_cash_flow,
            }
            
            # Get opening and closing cash balances
            total_cash = sum(b.get("Balance", 0) for b in bank_accounts)
            
            return {
                "report": "Cash Flow Statement (Derived)",
                "period": {
                    "from": from_date,
                    "to": to_date,
                },
                "operating_activities": operating,
                "investing_activities": {
                    "net": 0.0,
                    "note": "Not categorized in derived report",
                },
                "financing_activities": {
                    "net": 0.0,
                    "note": "Not categorized in derived report",
                },
                "summary": {
                    "net_cash_flow": net_cash_flow,
                    "closing_cash_balance": total_cash,
                    "total_receipts": total_receipts,
                    "total_payments": total_payments,
                    "receipt_count": len(receipts),
                    "payment_count": len(payments),
                },
                "note": "This is a simplified cash flow derived from receipts and payments. "
                        "For detailed categorization, use the native Manager.io report when available.",
            }
            
        except Exception as e:
            logger.error(f"Error generating derived cash flow: {e}")
            return {"error": str(e)}
    
    async def get_trial_balance(self, as_of_date: Optional[str] = None) -> dict:
        """Fetch trial balance from Manager.io.
        
        Args:
            as_of_date: Optional date in YYYY-MM-DD format
            
        Returns:
            Trial balance with all account debits/credits
            
        Note:
            Falls back to derived report from GL Summary if native endpoint fails.
        """
        form_data = {}
        if as_of_date:
            form_data["Date"] = as_of_date
        
        # Try native endpoint first
        result = await self._get_report_view(
            "/trial-balance-form",
            "/trial-balance-view",
            form_data,
        )
        
        # If native fails, use derived version
        if "error" in result:
            logger.info("Native trial balance failed, using derived version")
            return await self.get_trial_balance_derived(as_of_date)
        
        return result
    
    async def get_general_ledger_summary(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> dict:
        """Fetch general ledger summary from Manager.io.
        
        Args:
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            
        Returns:
            General ledger summary with account movements
        """
        form_data = {}
        if from_date:
            form_data["FromDate"] = from_date
        if to_date:
            form_data["ToDate"] = to_date
        
        return await self._get_report_view(
            "/general-ledger-summary-form",
            "/general-ledger-summary-view",
            form_data,
        )
    
    async def get_general_ledger_transactions(
        self,
        account_key: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> dict:
        """Fetch general ledger transactions from Manager.io.
        
        Args:
            account_key: Optional account key to filter by
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            
        Returns:
            General ledger transactions
        """
        form_data = {}
        if account_key:
            form_data["Account"] = account_key
        if from_date:
            form_data["FromDate"] = from_date
        if to_date:
            form_data["ToDate"] = to_date
        
        return await self._get_report_view(
            "/general-ledger-transactions-form",
            "/general-ledger-transactions-view",
            form_data,
        )
    
    async def get_aged_receivables(self) -> dict:
        """Fetch aged receivables report from Manager.io.
        
        Returns:
            Aged receivables data showing outstanding customer invoices by age
        """
        # Try the proper report endpoint first
        try:
            result = await self._get_report_view(
                "/aged-receivables-form",
                "/aged-receivables-view",
                {},
            )
            if "error" not in result:
                return result
        except Exception:
            pass
        
        # Fallback: Get sales invoices and filter for unpaid
        try:
            invoices = await self._get_paginated("/sales-invoices", skip=0, take=100)
            unpaid = [inv for inv in invoices.items 
                     if inv.get("status") not in ["PaidInFull", "Paid"]]
            
            return {
                "report": "Aged Receivables",
                "total_invoices": len(invoices.items),
                "unpaid_invoices": len(unpaid),
                "unpaid_details": unpaid[:20],
            }
        except Exception as e:
            return {"error": str(e)}
    
    async def get_aged_payables(self) -> dict:
        """Fetch aged payables report from Manager.io.
        
        Returns:
            Aged payables data showing outstanding supplier invoices by age
        """
        # Try the proper report endpoint first
        try:
            result = await self._get_report_view(
                "/aged-payables-form",
                "/aged-payables-view",
                {},
            )
            if "error" not in result:
                return result
        except Exception:
            pass
        
        # Fallback: Get purchase invoices and filter for unpaid
        try:
            invoices = await self._get_paginated("/purchase-invoices", skip=0, take=100)
            unpaid = [inv for inv in invoices.items 
                     if inv.get("status") not in ["PaidInFull", "Paid"]]
            
            return {
                "report": "Aged Payables",
                "total_invoices": len(invoices.items),
                "unpaid_invoices": len(unpaid),
                "unpaid_details": unpaid[:20],
            }
        except Exception as e:
            return {"error": str(e)}
    
    # =========================================================================
    # Derived Reports (from General Ledger Summary)
    # =========================================================================
    # These methods work around Manager.io API bugs where the native report
    # endpoints return NullReferenceException errors.
    # 
    # The GL Summary already provides proper categorization by Manager.io
    # based on account types. We just transform it into a cleaner format.
    
    def _extract_gl_value(self, cells: list, index: int) -> float:
        """Extract numeric value from GL Summary cells.
        
        Args:
            cells: List of cell dictionaries from GL Summary row
            index: Column index (0=Opening, 1=Debits, 2=Credits, 3=Net, 4=Closing)
            
        Returns:
            Float value or 0.0 if not found
        """
        if not cells or index >= len(cells):
            return 0.0
        cell = cells[index]
        if isinstance(cell, dict):
            return float(cell.get("Value", 0) or 0)
        return 0.0
    
    def _flatten_gl_rows(self, rows: list, group_name: str = "", depth: int = 0) -> list:
        """Recursively flatten GL Summary rows into a list of accounts.
        
        Args:
            rows: List of GL rows to process
            group_name: Parent group name for context
            depth: Current nesting depth
            
        Returns:
            List of account dictionaries with all column values
        """
        accounts = []
        
        for row in rows:
            name = row.get("Name", "")
            cells = row.get("Cells", [])
            sub_rows = row.get("Rows", [])
            
            if cells and len(cells) >= 4:
                # This is an account with values
                opening = self._extract_gl_value(cells, 0)
                debits = self._extract_gl_value(cells, 1)
                credits = self._extract_gl_value(cells, 2)
                net_movement = self._extract_gl_value(cells, 3)
                closing = self._extract_gl_value(cells, 4) if len(cells) > 4 else None
                
                # Only include if there's activity
                if debits != 0 or credits != 0 or (closing is not None and closing != 0):
                    accounts.append({
                        "group": group_name,
                        "account": name,
                        "opening": opening,
                        "debits": debits,
                        "credits": credits,
                        "net_movement": net_movement,
                        "closing": closing,
                        "depth": depth,
                    })
            
            if sub_rows:
                # Recurse into sub-rows
                sub_group = name if name else group_name
                accounts.extend(self._flatten_gl_rows(sub_rows, sub_group, depth + 1))
        
        return accounts
    
    async def get_profit_and_loss_derived(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> dict:
        """Generate P&L report from General Ledger Summary.
        
        This transforms the GL Summary into a P&L format. The GL Summary
        already categorizes accounts by type (Revenue, Expenses, etc.)
        based on Manager.io's chart of accounts configuration.
        
        For P&L accounts, we use the Net Movement column (column 3) which
        shows the activity for the period. Credits (negative) = income,
        Debits (positive) = expenses.
        
        Args:
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            
        Returns:
            P&L report with sections from GL Summary
        """
        try:
            gl_data = await self.get_general_ledger_summary(from_date, to_date)
            
            if "error" in gl_data:
                return gl_data
            
            # Process GL Summary - P&L sections come before balance sheet sections
            # Manager.io structures it as: P&L groups -> "Profit (loss)" -> BS groups
            sections = []
            total_income = 0.0
            total_expenses = 0.0
            found_profit_line = False
            
            for row in gl_data.get("Rows", []):
                group_name = row.get("Name", "").strip()
                
                # Stop at balance sheet sections (Assets, Liabilities, Equity)
                if group_name.lower() in ["assets", "liabilities", "equity"]:
                    break
                
                # Skip empty groups and summary lines
                sub_rows = row.get("Rows", [])
                if not sub_rows:
                    # Check if this is a profit/loss summary line
                    if "profit" in group_name.lower() or "loss" in group_name.lower():
                        found_profit_line = True
                    continue
                
                # Process accounts in this group
                accounts = []
                group_total = 0.0
                
                for subrow in sub_rows:
                    account_name = subrow.get("Name", "")
                    cells = subrow.get("Cells", [])
                    
                    # Use Net movement (column 3) for P&L
                    net = self._extract_gl_value(cells, 3)
                    debits = self._extract_gl_value(cells, 1)
                    credits = self._extract_gl_value(cells, 2)
                    
                    if net != 0 or debits != 0 or credits != 0:
                        accounts.append({
                            "name": account_name,
                            "debits": debits,
                            "credits": credits,
                            "net": net,
                            "amount": abs(net),
                        })
                        group_total += net
                
                if accounts:
                    # Determine if income or expense based on net movement sign
                    # Credits (negative net) = income, Debits (positive net) = expense
                    is_income = group_total < 0
                    
                    sections.append({
                        "name": group_name,
                        "accounts": accounts,
                        "total": abs(group_total),
                        "type": "income" if is_income else "expense",
                    })
                    
                    if is_income:
                        total_income += abs(group_total)
                    else:
                        total_expenses += abs(group_total)
            
            net_profit = total_income - total_expenses
            
            return {
                "report": "Profit and Loss Statement (Derived from GL Summary)",
                "subtitle": gl_data.get("Subtitle", ""),
                "period": {"from": from_date, "to": to_date},
                "sections": sections,
                "summary": {
                    "total_income": total_income,
                    "total_expenses": total_expenses,
                    "net_profit": net_profit,
                },
                "note": "Generated from General Ledger Summary. Income shown as credits, expenses as debits.",
            }
            
        except Exception as e:
            logger.error(f"Error generating derived P&L: {e}")
            return {"error": str(e)}
    
    async def get_balance_sheet_derived(
        self,
        as_of_date: Optional[str] = None,
    ) -> dict:
        """Generate Balance Sheet from General Ledger Summary.
        
        This transforms the GL Summary into a Balance Sheet format.
        Manager.io's GL Summary includes Assets, Liabilities, and Equity
        sections with closing balances.
        
        Sign convention:
        - Assets: Debit balances (positive closing)
        - Liabilities: Credit balances (negative closing, shown as positive)
        - Equity: Credit balances (negative closing, shown as positive)
        
        Args:
            as_of_date: Date in YYYY-MM-DD format
            
        Returns:
            Balance sheet with assets, liabilities, equity sections
        """
        
        def process_section(rows: list, negate: bool = False) -> tuple:
            """Process a balance sheet section recursively."""
            accounts = []
            total = 0.0
            
            for row in rows:
                name = row.get("Name", "")
                cells = row.get("Cells", [])
                sub_rows = row.get("Rows", [])
                
                if cells and len(cells) > 4:
                    closing = self._extract_gl_value(cells, 4)
                    if negate:
                        closing = -closing
                    if closing != 0:
                        accounts.append({"name": name, "balance": closing})
                        total += closing
                
                if sub_rows:
                    sub_accounts, sub_total = process_section(sub_rows, negate)
                    if sub_accounts:
                        accounts.append({
                            "name": name,
                            "is_group": True,
                            "accounts": sub_accounts,
                            "total": sub_total,
                        })
                        total += sub_total
            
            return accounts, total
        
        try:
            # Get GL Summary with full history for balance sheet
            gl_data = await self.get_general_ledger_summary(
                from_date="2000-01-01",
                to_date=as_of_date,
            )
            
            if "error" in gl_data:
                return gl_data
            
            # Find and process balance sheet sections
            assets = {"accounts": [], "total": 0.0}
            liabilities = {"accounts": [], "total": 0.0}
            equity = {"accounts": [], "total": 0.0}
            
            for row in gl_data.get("Rows", []):
                group_name = row.get("Name", "").strip().lower()
                sub_rows = row.get("Rows", [])
                
                if "asset" in group_name:
                    accts, total = process_section(sub_rows, negate=False)
                    assets["accounts"].extend(accts)
                    assets["total"] += total
                elif "liabilit" in group_name:
                    # Liabilities are credit balances - negate to show as positive
                    accts, total = process_section(sub_rows, negate=True)
                    liabilities["accounts"].extend(accts)
                    liabilities["total"] += total
                elif "equity" in group_name:
                    # Equity is credit balance - negate to show as positive
                    accts, total = process_section(sub_rows, negate=True)
                    equity["accounts"].extend(accts)
                    equity["total"] += total
            
            total_le = liabilities["total"] + equity["total"]
            
            return {
                "report": "Balance Sheet (Derived from GL Summary)",
                "subtitle": gl_data.get("Subtitle", ""),
                "as_of_date": as_of_date,
                "assets": assets,
                "liabilities": liabilities,
                "equity": equity,
                "summary": {
                    "total_assets": assets["total"],
                    "total_liabilities": liabilities["total"],
                    "total_equity": equity["total"],
                    "total_liabilities_and_equity": total_le,
                    "balanced": abs(assets["total"] - total_le) < 0.01,
                },
                "note": "Generated from General Ledger Summary closing balances.",
            }
            
        except Exception as e:
            logger.error(f"Error generating derived balance sheet: {e}")
            return {"error": str(e)}
    
    async def get_trial_balance_derived(
        self,
        as_of_date: Optional[str] = None,
    ) -> dict:
        """Generate Trial Balance from General Ledger Summary.
        
        Lists all accounts with their debit or credit balances.
        The trial balance should always balance (total debits = total credits).
        
        Args:
            as_of_date: Date in YYYY-MM-DD format
            
        Returns:
            Trial balance with all accounts
        """
        try:
            gl_data = await self.get_general_ledger_summary(
                from_date="2000-01-01",
                to_date=as_of_date,
            )
            
            if "error" in gl_data:
                return gl_data
            
            # Flatten all accounts
            accounts = []
            total_debits = 0.0
            total_credits = 0.0
            
            for row in gl_data.get("Rows", []):
                group_name = row.get("Name", "")
                flat_accounts = self._flatten_gl_rows(row.get("Rows", []), group_name)
                
                for acc in flat_accounts:
                    closing = acc.get("closing")
                    if closing is None:
                        continue
                    
                    if closing > 0:
                        debit = closing
                        credit = 0.0
                    else:
                        debit = 0.0
                        credit = abs(closing)
                    
                    if debit != 0 or credit != 0:
                        accounts.append({
                            "group": acc["group"],
                            "account": acc["account"],
                            "debit": debit,
                            "credit": credit,
                        })
                        total_debits += debit
                        total_credits += credit
            
            return {
                "report": "Trial Balance (Derived from GL Summary)",
                "subtitle": gl_data.get("Subtitle", ""),
                "as_of_date": as_of_date,
                "accounts": accounts,
                "summary": {
                    "total_debits": total_debits,
                    "total_credits": total_credits,
                    "balanced": abs(total_debits - total_credits) < 0.01,
                },
            }
            
        except Exception as e:
            logger.error(f"Error generating derived trial balance: {e}")
            return {"error": str(e)}
    
    # =========================================================================
    # Generic API Method (for any endpoint)
    # =========================================================================
    
    async def call_api(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
    ) -> dict:
        """Generic method to call any Manager.io API endpoint.
        
        This is a fallback for endpoints not covered by specific methods.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path (e.g., "/receipts", "/expense-claims")
            params: Optional query parameters
            data: Optional JSON body for POST/PUT
            
        Returns:
            API response as dictionary
        """
        try:
            client = await self._get_client()
            url = f"{self.base_url}{endpoint}"
            
            method = method.upper()
            if method == "GET":
                response = await client.get(url, params=params)
            elif method == "POST":
                response = await client.post(url, params=params, json=data)
            elif method == "PUT":
                response = await client.put(url, params=params, json=data)
            elif method == "DELETE":
                response = await client.delete(url, params=params)
            else:
                return {"error": f"Unsupported method: {method}"}
            
            self._handle_response_error(response)
            return response.json()
            
        except Exception as e:
            logger.error(f"Generic API call error: {method} {endpoint} - {e}")
            return {"error": str(e)}
    
    # =========================================================================
    # Bank Account Methods
    # =========================================================================
    
    async def get_bank_accounts(self) -> List[dict]:
        """Fetch bank and cash accounts from Manager.io.
        
        Returns:
            List of bank/cash account dictionaries with normalized field names
        """
        endpoint = "/bank-and-cash-accounts"
        data = await self._get(endpoint, use_cache=True)
        
        # Handle different response formats
        records = []
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            # Manager.io returns data under 'bankAndCashAccounts' key
            records = data.get("bankAndCashAccounts", 
                      data.get("items", 
                      data.get("data", [])))
        
        # Normalize the records to have consistent field names
        normalized = []
        for record in records:
            # Extract balance from nested structure if present
            balance = 0.0
            if "actualBalance" in record:
                ab = record["actualBalance"]
                if isinstance(ab, dict):
                    balance = float(ab.get("value", 0))
                else:
                    balance = float(ab or 0)
            elif "Balance" in record or "balance" in record:
                balance = float(record.get("Balance") or record.get("balance") or 0)
            
            key_val = record.get("key") or record.get("Key") or ""
            name_val = record.get("name") or record.get("Name") or "Unknown"
            currency_val = record.get("actualBalance", {}).get("currency", "USD") if isinstance(record.get("actualBalance"), dict) else "USD"
            
            normalized.append({
                # Uppercase keys (primary)
                "Key": key_val,
                "Name": name_val,
                "Balance": balance,
                "Currency": currency_val,
                # Lowercase keys (for compatibility)
                "key": key_val,
                "name": name_val,
                "balance": balance,
                "currency": currency_val,
                "_raw": record,  # Keep raw data for debugging
            })
        
        return normalized
    
    async def get_bank_account_transactions(
        self,
        account_key: str,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch transactions for a specific bank account.
        
        Args:
            account_key: Bank account key/UUID
            skip: Number of records to skip
            take: Number of records to return
            
        Returns:
            PaginatedResponse with transaction records
        """
        endpoint = f"/bank-account-transactions/{account_key}"
        params = {"skip": skip, "take": take}
        
        data = await self._get(endpoint, params=params, use_cache=False)
        
        if isinstance(data, list):
            items = data
            total = len(items) + skip
        elif isinstance(data, dict):
            items = data.get("items", data.get("data", []))
            total = data.get("total", data.get("count", len(items) + skip))
        else:
            items = []
            total = 0
        
        return PaginatedResponse(items=items, total=total, skip=skip, take=take)
    
    # =========================================================================
    # Employee Methods
    # =========================================================================
    
    async def get_employees(self) -> List[dict]:
        """Fetch employees from Manager.io.
        
        Returns:
            List of employee dictionaries with normalized field names
        """
        endpoint = "/employees"
        data = await self._get(endpoint, use_cache=True)
        
        records = []
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            # Manager.io returns data under 'employees' key
            records = data.get("employees", 
                      data.get("items", 
                      data.get("data", [])))
        
        # Normalize records
        normalized = []
        for record in records:
            normalized.append({
                "Key": record.get("key") or record.get("Key") or "",
                "Name": record.get("name") or record.get("Name") or "",
                "key": record.get("key") or record.get("Key") or "",
                "name": record.get("name") or record.get("Name") or "",
                "_raw": record,
            })
        return normalized
    
    # =========================================================================
    # Credit Note Methods
    # =========================================================================
    
    async def get_credit_notes(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch credit notes from Manager.io.
        
        Args:
            skip: Number of records to skip
            take: Number of records to return
            
        Returns:
            PaginatedResponse with credit note records
        """
        return await self._get_paginated("/credit-notes", skip=skip, take=take)
    
    # =========================================================================
    # Inventory Methods
    # =========================================================================
    
    async def get_inventory_items(self) -> List[dict]:
        """Fetch inventory items from Manager.io.
        
        Returns:
            List of inventory item dictionaries with fields like:
            ItemCode, ItemName, QtyOnHand, AverageCost, SalePrice, etc.
        """
        endpoint = "/inventory-items"
        data = await self._get(endpoint, use_cache=True)
        
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Manager.io returns data under 'inventoryItems' key
            return data.get("inventoryItems", 
                   data.get("items", 
                   data.get("data", [])))
        return []
    
    async def get_inventory_kits(self) -> List[dict]:
        """Fetch inventory kits from Manager.io.
        
        Returns:
            List of inventory kit dictionaries
        """
        endpoint = "/inventory-kits"
        data = await self._get(endpoint, use_cache=True)
        
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Manager.io returns data under 'inventoryKits' key
            return data.get("inventoryKits", 
                   data.get("items", 
                   data.get("data", [])))
        return []
    
    async def get_inventory_unit_costs(self) -> List[dict]:
        """Fetch inventory unit costs from Manager.io.
        
        Returns:
            List of inventory unit cost records
        """
        endpoint = "/inventory-unit-costs"
        data = await self._get(endpoint, use_cache=False)
        
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Manager.io returns data under 'inventoryUnitCosts' key
            return data.get("inventoryUnitCosts", 
                   data.get("items", 
                   data.get("data", [])))
        return []
    
    # =========================================================================
    # Debit Notes
    # =========================================================================
    
    async def get_debit_notes(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch debit notes from Manager.io."""
        return await self._get_paginated("/debit-notes", skip=skip, take=take)
    
    # =========================================================================
    # Sales & Purchase Invoices (List)
    # =========================================================================
    
    async def get_sales_invoices(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch sales invoices from Manager.io."""
        return await self._get_paginated("/sales-invoices", skip=skip, take=take)
    
    async def get_purchase_invoices(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch purchase invoices from Manager.io."""
        return await self._get_paginated("/purchase-invoices", skip=skip, take=take)
    
    # =========================================================================
    # Orders
    # =========================================================================
    
    async def get_sales_orders(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch sales orders from Manager.io."""
        return await self._get_paginated("/sales-orders", skip=skip, take=take)
    
    async def get_purchase_orders(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch purchase orders from Manager.io."""
        return await self._get_paginated("/purchase-orders", skip=skip, take=take)
    
    # =========================================================================
    # Goods Receipts & Delivery Notes
    # =========================================================================
    
    async def get_goods_receipts(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch goods receipts from Manager.io."""
        return await self._get_paginated("/goods-receipts", skip=skip, take=take)
    
    async def get_delivery_notes(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch delivery notes from Manager.io."""
        return await self._get_paginated("/delivery-notes", skip=skip, take=take)
    
    # =========================================================================
    # Tax Codes
    # =========================================================================
    
    async def get_tax_codes(self) -> List[dict]:
        """Fetch tax codes from Manager.io."""
        endpoint = "/tax-codes"
        data = await self._get(endpoint, use_cache=True)
        
        records = []
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get("taxCodes", 
                      data.get("items", 
                      data.get("data", [])))
        
        # Normalize records
        normalized = []
        for record in records:
            normalized.append({
                "Key": record.get("key") or record.get("Key") or "",
                "Name": record.get("name") or record.get("Name") or "",
                "Rate": record.get("rate") or record.get("Rate") or 0,
                "key": record.get("key") or record.get("Key") or "",
                "name": record.get("name") or record.get("Name") or "",
                "_raw": record,
            })
        return normalized
    
    # =========================================================================
    # Fixed Assets & Projects
    # =========================================================================
    
    async def get_fixed_assets(self) -> List[dict]:
        """Fetch fixed assets from Manager.io."""
        endpoint = "/fixed-assets"
        data = await self._get(endpoint, use_cache=True)
        
        records = []
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get("fixedAssets", 
                      data.get("items", 
                      data.get("data", [])))
        
        # Normalize records
        normalized = []
        for record in records:
            normalized.append({
                "Key": record.get("key") or record.get("Key") or "",
                "Name": record.get("name") or record.get("Name") or "",
                "key": record.get("key") or record.get("Key") or "",
                "name": record.get("name") or record.get("Name") or "",
                "_raw": record,
            })
        return normalized
    
    async def get_projects(self) -> List[dict]:
        """Fetch projects from Manager.io."""
        endpoint = "/projects"
        data = await self._get(endpoint, use_cache=True)
        
        records = []
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get("projects", 
                      data.get("items", 
                      data.get("data", [])))
        
        # Normalize records
        normalized = []
        for record in records:
            normalized.append({
                "Key": record.get("key") or record.get("Key") or "",
                "Name": record.get("name") or record.get("Name") or "",
                "key": record.get("key") or record.get("Key") or "",
                "name": record.get("name") or record.get("Name") or "",
                "_raw": record,
            })
        return normalized
    
    # =========================================================================
    # Credit Note & Debit Note Creation
    # =========================================================================
    
    async def create_credit_note(self, data: dict) -> CreateResponse:
        """Create a credit note in Manager.io.
        
        Args:
            data: Credit note data in Manager.io API format
            
        Returns:
            CreateResponse with success status and entry key
        """
        endpoint = "/credit-note-form"
        try:
            response_data = await self._post(endpoint, data)
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                entry_key = response_data
            return CreateResponse(success=True, key=entry_key, message="Credit note created successfully")
        except ManagerIOError as e:
            return CreateResponse(success=False, key=None, message=str(e))
    
    async def create_debit_note(self, data: dict) -> CreateResponse:
        """Create a debit note in Manager.io.
        
        Args:
            data: Debit note data in Manager.io API format
            
        Returns:
            CreateResponse with success status and entry key
        """
        endpoint = "/debit-note-form"
        try:
            response_data = await self._post(endpoint, data)
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                entry_key = response_data
            return CreateResponse(success=True, key=entry_key, message="Debit note created successfully")
        except ManagerIOError as e:
            return CreateResponse(success=False, key=None, message=str(e))
    
    # =========================================================================
    # Inventory Operations
    # =========================================================================
    
    async def create_goods_receipt(self, data: dict) -> CreateResponse:
        """Create a goods receipt in Manager.io.
        
        Records inventory received from a supplier.
        
        Args:
            data: Goods receipt data in Manager.io API format
            
        Returns:
            CreateResponse with success status and entry key
        """
        endpoint = "/goods-receipt-form"
        try:
            response_data = await self._post(endpoint, data)
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                entry_key = response_data
            return CreateResponse(success=True, key=entry_key, message="Goods receipt created successfully")
        except ManagerIOError as e:
            return CreateResponse(success=False, key=None, message=str(e))
    
    async def create_inventory_write_off(self, data: dict) -> CreateResponse:
        """Create an inventory write-off in Manager.io.
        
        Records inventory that is damaged, lost, or otherwise removed from stock.
        
        Args:
            data: Inventory write-off data in Manager.io API format
            
        Returns:
            CreateResponse with success status and entry key
        """
        endpoint = "/inventory-write-off-form"
        try:
            response_data = await self._post(endpoint, data)
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                entry_key = response_data
            return CreateResponse(success=True, key=entry_key, message="Inventory write-off created successfully")
        except ManagerIOError as e:
            return CreateResponse(success=False, key=None, message=str(e))
    
    async def create_inventory_transfer(self, data: dict) -> CreateResponse:
        """Create an inventory transfer in Manager.io.
        
        Moves inventory between locations.
        
        Args:
            data: Inventory transfer data in Manager.io API format
            
        Returns:
            CreateResponse with success status and entry key
        """
        endpoint = "/inventory-transfer-form"
        try:
            response_data = await self._post(endpoint, data)
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                entry_key = response_data
            return CreateResponse(success=True, key=entry_key, message="Inventory transfer created successfully")
        except ManagerIOError as e:
            return CreateResponse(success=False, key=None, message=str(e))
    
    # =========================================================================
    # Investment Methods
    # =========================================================================
    
    async def get_investments(self) -> List[dict]:
        """Fetch investments from Manager.io.
        
        Returns:
            List of investment dictionaries (stocks, bonds, etc.)
        """
        endpoint = "/investments"
        data = await self._get(endpoint, use_cache=True)
        
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Manager.io returns data under 'investments' key
            return data.get("investments", 
                   data.get("items", 
                   data.get("data", [])))
        return []
    
    async def get_investment_transactions(
        self,
        skip: int = 0,
        take: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Fetch investment transactions from Manager.io."""
        return await self._get_paginated("/investment-transactions", skip=skip, take=take)
    
    async def get_investment_market_prices(self) -> List[dict]:
        """Fetch investment market prices from Manager.io.
        
        Returns:
            List of market price records
        """
        endpoint = "/investment-market-prices"
        data = await self._get(endpoint, use_cache=False)
        
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Manager.io returns data under 'investmentMarketPrices' key
            return data.get("investmentMarketPrices", 
                   data.get("items", 
                   data.get("data", [])))
        return []
    
    async def create_investment(self, data: dict) -> CreateResponse:
        """Create an investment in Manager.io.
        
        Note: The API endpoint has a typo (/inventment-form instead of /investment-form).
        
        Args:
            data: Investment data in Manager.io API format
            
        Returns:
            CreateResponse with success status and entry key
        """
        # Note: API has typo - "inventment" instead of "investment"
        endpoint = "/inventment-form"
        try:
            response_data = await self._post(endpoint, data)
            entry_key = None
            if isinstance(response_data, dict):
                entry_key = response_data.get("Key", response_data.get("key"))
            elif isinstance(response_data, str):
                entry_key = response_data
            return CreateResponse(success=True, key=entry_key, message="Investment created successfully")
        except ManagerIOError as e:
            return CreateResponse(success=False, key=None, message=str(e))
    
    # =========================================================================
    # Delete Methods
    # =========================================================================
    
    async def _delete(self, endpoint: str) -> Any:
        """Make a DELETE request.
        
        Args:
            endpoint: API endpoint path
            
        Returns:
            Response JSON data
        """
        response = await self._request_with_retry("DELETE", endpoint)
        try:
            return response.json()
        except Exception:
            return {"success": True}
    
    async def delete_entry(self, entry_type: str, entry_id: str) -> DeleteResponse:
        """Delete an entry from Manager.io.
        
        Args:
            entry_type: Type of entry (e.g., "expense-claim-form")
            entry_id: Entry UUID
            
        Returns:
            DeleteResponse with success status
        """
        if not entry_type:
            raise ManagerIOValidationError("Entry type is required")
        if not entry_id:
            raise ManagerIOValidationError("Entry ID is required")
        
        endpoint = f"/{entry_type.lstrip('/')}/{entry_id}"
        
        try:
            await self._delete(endpoint)
            return DeleteResponse(success=True, message="Entry deleted successfully")
        except ManagerIONotFoundError:
            raise
        except ManagerIOError as e:
            return DeleteResponse(success=False, message=str(e))
