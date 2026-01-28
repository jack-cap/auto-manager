"""LangChain agent tools for Manager.io bookkeeping operations.

This module provides LangChain tools that wrap the ManagerIOClient methods
for use by the AI agent. Tools handle:
- Data fetching (accounts, suppliers, customers, transactions)
- Balance calculations
- Document processing (OCR, expense categorization, supplier matching)
- Error handling and logging

Tools require access to company configuration to get API credentials.
"""

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import CompanyConfig
from app.services.company import CompanyConfigService, CompanyNotFoundError
from app.services.encryption import EncryptionService
from app.services.manager_io import (
    Account,
    Customer,
    ManagerIOClient,
    ManagerIOError,
    Supplier,
)
from app.services.ocr import OCRError, OCRResult, OCRService

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models for Tool Responses
# =============================================================================


class Transaction(BaseModel):
    """Represents a transaction from Manager.io."""
    
    key: str = Field(description="Unique identifier for the transaction")
    date: str = Field(description="Transaction date in YYYY-MM-DD format")
    description: str = Field(description="Transaction description")
    amount: float = Field(description="Transaction amount")
    account: Optional[str] = Field(default=None, description="Account name or key")
    transaction_type: str = Field(description="Type of transaction (payment, receipt, transfer, journal)")
    reference: Optional[str] = Field(default=None, description="Reference number if available")


class AccountBalance(BaseModel):
    """Represents an account balance."""
    
    account_key: str = Field(description="Account key/UUID")
    account_name: str = Field(description="Account name")
    balance: float = Field(description="Current balance")
    currency: str = Field(default="USD", description="Currency code")


class AccountBalances(BaseModel):
    """Collection of account balances."""
    
    balances: List[AccountBalance] = Field(description="List of account balances")
    as_of_date: str = Field(description="Date the balances were calculated")
    total_assets: float = Field(default=0.0, description="Total assets")
    total_liabilities: float = Field(default=0.0, description="Total liabilities")


class ExtractedData(BaseModel):
    """Data extracted from a document via OCR.
    
    Attributes:
        text: Raw extracted text from the document
        normalized_text: Text with full-width characters converted to half-width
        pages: Number of pages processed (for PDFs)
        success: Whether extraction was successful
        error: Error message if extraction failed
    """
    text: str = Field(description="Raw extracted text from the document")
    normalized_text: str = Field(description="Normalized text (full-width to half-width)")
    pages: int = Field(default=1, description="Number of pages processed")
    success: bool = Field(default=True, description="Whether extraction was successful")
    error: Optional[str] = Field(default=None, description="Error message if extraction failed")


class MatchedAccount(BaseModel):
    """Result of expense categorization matching.
    
    Attributes:
        key: Account key/UUID
        name: Account name
        code: Account code (optional)
        score: Match confidence score (0.0 to 1.0)
        matched_keywords: Keywords that contributed to the match
    """
    key: str = Field(description="Account key/UUID")
    name: str = Field(description="Account name")
    code: Optional[str] = Field(default=None, description="Account code")
    score: float = Field(description="Match confidence score (0.0 to 1.0)")
    matched_keywords: List[str] = Field(default_factory=list, description="Keywords that contributed to the match")


class MatchedSupplier(BaseModel):
    """Result of supplier identification matching.
    
    Attributes:
        key: Supplier key/UUID
        name: Supplier name
        score: Match confidence score (0.0 to 1.0)
        matched: Whether a match was found above threshold
    """
    key: str = Field(description="Supplier key/UUID")
    name: str = Field(description="Supplier name")
    score: float = Field(description="Match confidence score (0.0 to 1.0)")
    matched: bool = Field(default=True, description="Whether a match was found above threshold")


# =============================================================================
# Tool Context Manager
# =============================================================================


class ToolContext:
    """Context manager for agent tools providing access to services.
    
    This class manages the dependencies needed by agent tools:
    - Database session for company configuration lookup
    - Redis cache for Manager.io client caching
    - Encryption service for API key decryption
    - OCR service for document text extraction
    
    Example:
        ```python
        context = ToolContext(db_session, redis_client)
        client = await context.get_manager_io_client(company_id, user_id)
        accounts = await client.get_chart_of_accounts()
        ```
    """
    
    def __init__(
        self,
        db: AsyncSession,
        redis: Optional[Redis] = None,
        encryption_service: Optional[EncryptionService] = None,
        ocr_service: Optional[OCRService] = None,
    ):
        """Initialize ToolContext.
        
        Args:
            db: Async SQLAlchemy session
            redis: Optional Redis client for caching
            encryption_service: Optional encryption service for API key decryption
            ocr_service: Optional OCR service for document text extraction
        """
        self.db = db
        self.redis = redis
        self._encryption = encryption_service or EncryptionService()
        self._ocr_service = ocr_service
        self._company_service = CompanyConfigService(db, self._encryption)
        self._clients: Dict[str, ManagerIOClient] = {}
    
    async def get_company_config(
        self,
        company_id: str,
        user_id: str,
    ) -> CompanyConfig:
        """Get company configuration with access control.
        
        Args:
            company_id: Company configuration ID
            user_id: User ID for access control
            
        Returns:
            CompanyConfig instance
            
        Raises:
            CompanyNotFoundError: If company not found or access denied
        """
        return await self._company_service.get_by_id(company_id, user_id)
    
    async def get_manager_io_client(
        self,
        company_id: str,
        user_id: str,
    ) -> ManagerIOClient:
        """Get or create a ManagerIOClient for a company.
        
        Clients are cached by company_id to reuse connections.
        
        Args:
            company_id: Company configuration ID
            user_id: User ID for access control
            
        Returns:
            Configured ManagerIOClient instance
            
        Raises:
            CompanyNotFoundError: If company not found or access denied
        """
        # Check cache first
        cache_key = f"{company_id}:{user_id}"
        if cache_key in self._clients:
            return self._clients[cache_key]
        
        # Get company config
        company = await self.get_company_config(company_id, user_id)
        
        # Decrypt API key
        api_key = self._company_service.decrypt_api_key(company)
        
        # Create client
        client = ManagerIOClient(
            base_url=company.base_url,
            api_key=api_key,
            cache=self.redis,
        )
        
        # Cache client
        self._clients[cache_key] = client
        
        return client
    
    def get_ocr_service(self) -> OCRService:
        """Get the OCR service.
        
        Returns:
            Configured OCRService instance
            
        Raises:
            RuntimeError: If OCR service has not been configured
        """
        if self._ocr_service is None:
            # Create a default OCR service if not provided
            self._ocr_service = OCRService()
        return self._ocr_service
    
    async def close(self) -> None:
        """Close all cached clients."""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()


# Global tool context - must be set before using tools
_tool_context: Optional[ToolContext] = None


def set_tool_context(context: ToolContext) -> None:
    """Set the global tool context.
    
    Must be called before using any agent tools.
    
    Args:
        context: ToolContext instance with database and cache access
    """
    global _tool_context
    _tool_context = context


def get_tool_context() -> ToolContext:
    """Get the global tool context.
    
    Returns:
        Current ToolContext instance
        
    Raises:
        RuntimeError: If tool context has not been set
    """
    if _tool_context is None:
        raise RuntimeError(
            "Tool context not set. Call set_tool_context() before using agent tools."
        )
    return _tool_context


# =============================================================================
# Data Fetching Tools
# =============================================================================


@tool
async def get_chart_of_accounts(
    company_id: str,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Fetch chart of accounts from Manager.io for expense categorization.
    
    Retrieves the list of accounts configured in Manager.io, which can be used
    for categorizing expenses and matching transactions to the appropriate
    expense accounts.
    
    Args:
        company_id: The company configuration ID to fetch accounts for
        user_id: The user ID for access control
        
    Returns:
        List of account dictionaries with keys: key, name, code (optional)
        
    Raises:
        CompanyNotFoundError: If company not found or access denied
        ManagerIOError: If the Manager.io API request fails
    """
    logger.info(f"Fetching chart of accounts for company {company_id}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        accounts = await client.get_chart_of_accounts()
        
        # Convert to dictionaries for serialization
        result = [
            {"key": acc.key, "name": acc.name, "code": acc.code}
            for acc in accounts
        ]
        
        logger.info(f"Retrieved {len(result)} accounts for company {company_id}")
        return result
        
    except CompanyNotFoundError:
        logger.error(f"Company not found: {company_id}")
        raise
    except ManagerIOError as e:
        logger.error(f"Manager.io API error fetching accounts: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching accounts: {e}")
        raise ManagerIOError(f"Failed to fetch chart of accounts: {e}")


@tool
async def get_suppliers(
    company_id: str,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Fetch suppliers list from Manager.io for vendor matching.
    
    Retrieves the list of suppliers configured in Manager.io, which can be used
    for matching vendor names from documents to existing suppliers.
    
    Args:
        company_id: The company configuration ID to fetch suppliers for
        user_id: The user ID for access control
        
    Returns:
        List of supplier dictionaries with keys: key, name
        
    Raises:
        CompanyNotFoundError: If company not found or access denied
        ManagerIOError: If the Manager.io API request fails
    """
    logger.info(f"Fetching suppliers for company {company_id}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        suppliers = await client.get_suppliers()
        
        # Convert to dictionaries for serialization
        result = [
            {"key": sup.key, "name": sup.name}
            for sup in suppliers
        ]
        
        logger.info(f"Retrieved {len(result)} suppliers for company {company_id}")
        return result
        
    except CompanyNotFoundError:
        logger.error(f"Company not found: {company_id}")
        raise
    except ManagerIOError as e:
        logger.error(f"Manager.io API error fetching suppliers: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching suppliers: {e}")
        raise ManagerIOError(f"Failed to fetch suppliers: {e}")


@tool
async def get_customers(
    company_id: str,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Fetch customers list from Manager.io.
    
    Retrieves the list of customers configured in Manager.io, which can be used
    for matching customer names from documents.
    
    Args:
        company_id: The company configuration ID to fetch customers for
        user_id: The user ID for access control
        
    Returns:
        List of customer dictionaries with keys: key, name
        
    Raises:
        CompanyNotFoundError: If company not found or access denied
        ManagerIOError: If the Manager.io API request fails
    """
    logger.info(f"Fetching customers for company {company_id}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        customers = await client.get_customers()
        
        # Convert to dictionaries for serialization
        result = [
            {"key": cust.key, "name": cust.name}
            for cust in customers
        ]
        
        logger.info(f"Retrieved {len(result)} customers for company {company_id}")
        return result
        
    except CompanyNotFoundError:
        logger.error(f"Company not found: {company_id}")
        raise
    except ManagerIOError as e:
        logger.error(f"Manager.io API error fetching customers: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching customers: {e}")
        raise ManagerIOError(f"Failed to fetch customers: {e}")


@tool
async def get_recent_transactions(
    company_id: str,
    user_id: str,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch recent transactions for context.
    
    Retrieves recent transactions from Manager.io including payments, receipts,
    and transfers. This provides context for the agent when processing new
    documents.
    
    Args:
        company_id: The company configuration ID to fetch transactions for
        user_id: The user ID for access control
        limit: Maximum number of transactions to return (default: 50)
        
    Returns:
        List of transaction dictionaries with keys: key, date, description,
        amount, account, transaction_type, reference
        
    Raises:
        CompanyNotFoundError: If company not found or access denied
        ManagerIOError: If the Manager.io API request fails
    """
    logger.info(f"Fetching recent transactions for company {company_id}, limit={limit}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        transactions: List[Dict[str, Any]] = []
        
        # Calculate how many to fetch from each source
        # We'll fetch from payments, receipts, and transfers
        per_source_limit = max(limit // 3, 10)
        
        # Fetch payments
        try:
            payments_response = await client.get_payments(skip=0, take=per_source_limit)
            for item in payments_response.items:
                transactions.append({
                    "key": item.get("Key", item.get("key", "")),
                    "date": item.get("Date", item.get("date", "")),
                    "description": item.get("Description", item.get("description", "")),
                    "amount": float(item.get("Amount", item.get("amount", 0))),
                    "account": item.get("Account", item.get("account")),
                    "transaction_type": "payment",
                    "reference": item.get("Reference", item.get("reference")),
                })
        except ManagerIOError as e:
            logger.warning(f"Failed to fetch payments: {e}")
        
        # Fetch receipts
        try:
            receipts_response = await client.get_receipts(skip=0, take=per_source_limit)
            for item in receipts_response.items:
                transactions.append({
                    "key": item.get("Key", item.get("key", "")),
                    "date": item.get("Date", item.get("date", "")),
                    "description": item.get("Description", item.get("description", "")),
                    "amount": float(item.get("Amount", item.get("amount", 0))),
                    "account": item.get("Account", item.get("account")),
                    "transaction_type": "receipt",
                    "reference": item.get("Reference", item.get("reference")),
                })
        except ManagerIOError as e:
            logger.warning(f"Failed to fetch receipts: {e}")
        
        # Fetch transfers
        try:
            transfers_response = await client.get_transfers(skip=0, take=per_source_limit)
            for item in transfers_response.items:
                transactions.append({
                    "key": item.get("Key", item.get("key", "")),
                    "date": item.get("Date", item.get("date", "")),
                    "description": item.get("Description", item.get("description", "")),
                    "amount": float(item.get("Amount", item.get("amount", 0))),
                    "account": item.get("FromAccount", item.get("from_account")),
                    "transaction_type": "transfer",
                    "reference": item.get("Reference", item.get("reference")),
                })
        except ManagerIOError as e:
            logger.warning(f"Failed to fetch transfers: {e}")
        
        # Sort by date (most recent first) and limit
        transactions.sort(
            key=lambda x: x.get("date", ""),
            reverse=True,
        )
        transactions = transactions[:limit]
        
        logger.info(f"Retrieved {len(transactions)} recent transactions for company {company_id}")
        return transactions
        
    except CompanyNotFoundError:
        logger.error(f"Company not found: {company_id}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching transactions: {e}")
        raise ManagerIOError(f"Failed to fetch recent transactions: {e}")


@tool
async def get_account_balances(
    company_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Calculate current account balances from transaction history.
    
    Fetches all transactions (payments, receipts, transfers, journal entries)
    and calculates running balances for each account. This is useful for
    dashboard displays and financial reporting.
    
    Args:
        company_id: The company configuration ID to calculate balances for
        user_id: The user ID for access control
        
    Returns:
        Dictionary containing:
        - balances: List of account balance dictionaries
        - as_of_date: Date the balances were calculated
        - total_assets: Sum of asset account balances
        - total_liabilities: Sum of liability account balances
        
    Raises:
        CompanyNotFoundError: If company not found or access denied
        ManagerIOError: If the Manager.io API request fails
    """
    logger.info(f"Calculating account balances for company {company_id}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        # Get chart of accounts for account names
        accounts = await client.get_chart_of_accounts()
        account_map = {acc.key: acc.name for acc in accounts}
        
        # Initialize balance tracking
        balances: Dict[str, float] = {}
        
        # Fetch all payments (outflows)
        try:
            payments = await client.fetch_all_paginated("/payments")
            for payment in payments:
                account_key = payment.get("Account", payment.get("account", ""))
                amount = float(payment.get("Amount", payment.get("amount", 0)))
                if account_key:
                    balances[account_key] = balances.get(account_key, 0) - amount
        except ManagerIOError as e:
            logger.warning(f"Failed to fetch payments for balance calculation: {e}")
        
        # Fetch all receipts (inflows)
        try:
            receipts = await client.fetch_all_paginated("/receipts")
            for receipt in receipts:
                account_key = receipt.get("Account", receipt.get("account", ""))
                amount = float(receipt.get("Amount", receipt.get("amount", 0)))
                if account_key:
                    balances[account_key] = balances.get(account_key, 0) + amount
        except ManagerIOError as e:
            logger.warning(f"Failed to fetch receipts for balance calculation: {e}")
        
        # Fetch all transfers
        try:
            transfers = await client.fetch_all_paginated("/inter-account-transfers")
            for transfer in transfers:
                from_account = transfer.get("FromAccount", transfer.get("from_account", ""))
                to_account = transfer.get("ToAccount", transfer.get("to_account", ""))
                amount = float(transfer.get("Amount", transfer.get("amount", 0)))
                if from_account:
                    balances[from_account] = balances.get(from_account, 0) - amount
                if to_account:
                    balances[to_account] = balances.get(to_account, 0) + amount
        except ManagerIOError as e:
            logger.warning(f"Failed to fetch transfers for balance calculation: {e}")
        
        # Fetch journal entries for more detailed balance tracking
        try:
            journal_entries = await client.fetch_all_paginated("/journal-entry-lines")
            for entry in journal_entries:
                account_key = entry.get("Account", entry.get("account", ""))
                debit = float(entry.get("Debit", entry.get("debit", 0)) or 0)
                credit = float(entry.get("Credit", entry.get("credit", 0)) or 0)
                if account_key:
                    # Debits increase asset accounts, credits decrease them
                    # For liability accounts, it's the opposite
                    balances[account_key] = balances.get(account_key, 0) + debit - credit
        except ManagerIOError as e:
            logger.warning(f"Failed to fetch journal entries for balance calculation: {e}")
        
        # Build result
        balance_list = []
        total_assets = 0.0
        total_liabilities = 0.0
        
        for account_key, balance in balances.items():
            account_name = account_map.get(account_key, account_key)
            balance_list.append({
                "account_key": account_key,
                "account_name": account_name,
                "balance": round(balance, 2),
                "currency": "USD",  # Default currency
            })
            
            # Simple heuristic: positive balances are assets, negative are liabilities
            # In a real implementation, this would use account type from chart of accounts
            if balance > 0:
                total_assets += balance
            else:
                total_liabilities += abs(balance)
        
        # Sort by account name
        balance_list.sort(key=lambda x: x["account_name"])
        
        result = {
            "balances": balance_list,
            "as_of_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "total_assets": round(total_assets, 2),
            "total_liabilities": round(total_liabilities, 2),
        }
        
        logger.info(
            f"Calculated balances for {len(balance_list)} accounts, "
            f"total_assets={total_assets:.2f}, total_liabilities={total_liabilities:.2f}"
        )
        return result
        
    except CompanyNotFoundError:
        logger.error(f"Company not found: {company_id}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error calculating balances: {e}")
        raise ManagerIOError(f"Failed to calculate account balances: {e}")


# =============================================================================
# Document Processing Tools
# =============================================================================


# Expense category keywords for semantic matching
# Maps common expense keywords to account name patterns
EXPENSE_KEYWORDS: Dict[str, List[str]] = {
    # Office and supplies
    "office": ["office", "supplies", "stationery", "paper", "printer", "ink", "toner"],
    "supplies": ["supplies", "office", "stationery", "consumables"],
    
    # Travel and transportation
    "travel": ["travel", "transportation", "airfare", "flight", "hotel", "lodging", "accommodation"],
    "transport": ["transport", "taxi", "uber", "lyft", "parking", "fuel", "gas", "petrol", "mileage"],
    "parking": ["parking", "garage"],
    
    # Meals and entertainment
    "meals": ["meals", "food", "restaurant", "dining", "lunch", "dinner", "breakfast", "catering"],
    "entertainment": ["entertainment", "client", "hospitality"],
    
    # Utilities and services
    "utilities": ["utilities", "electric", "electricity", "water", "gas", "power", "energy"],
    "telephone": ["telephone", "phone", "mobile", "cell", "communications", "internet", "broadband"],
    "internet": ["internet", "broadband", "wifi", "network"],
    
    # Professional services
    "professional": ["professional", "consulting", "legal", "accounting", "audit", "advisory"],
    "legal": ["legal", "attorney", "lawyer", "law"],
    "accounting": ["accounting", "bookkeeping", "audit", "tax"],
    
    # Insurance and fees
    "insurance": ["insurance", "coverage", "premium", "policy"],
    "bank": ["bank", "banking", "fees", "charges", "interest"],
    
    # Rent and facilities
    "rent": ["rent", "lease", "rental", "premises", "office space"],
    "maintenance": ["maintenance", "repair", "repairs", "cleaning", "janitorial"],
    
    # Marketing and advertising
    "marketing": ["marketing", "advertising", "promotion", "ads", "campaign", "branding"],
    "advertising": ["advertising", "ads", "promotion", "media"],
    
    # Technology and software
    "software": ["software", "subscription", "saas", "license", "app", "application"],
    "hardware": ["hardware", "computer", "equipment", "device", "laptop", "monitor"],
    "technology": ["technology", "it", "tech", "computer"],
    
    # Training and education
    "training": ["training", "education", "course", "seminar", "workshop", "conference"],
    
    # Shipping and postage
    "shipping": ["shipping", "postage", "courier", "delivery", "freight", "mail"],
}


def _normalize_for_matching(text: str) -> str:
    """Normalize text for matching purposes.
    
    Converts to lowercase, removes special characters, and normalizes whitespace.
    
    Args:
        text: Input text to normalize
        
    Returns:
        Normalized text
    """
    # Convert to lowercase
    text = text.lower()
    # Remove special characters except spaces
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    # Normalize whitespace
    text = ' '.join(text.split())
    return text


def _extract_keywords(text: str) -> List[str]:
    """Extract keywords from text.
    
    Args:
        text: Input text
        
    Returns:
        List of keywords
    """
    normalized = _normalize_for_matching(text)
    # Split into words and filter short words
    words = [w for w in normalized.split() if len(w) >= 3]
    return words


def _calculate_keyword_score(
    description: str,
    account_name: str,
) -> Tuple[float, List[str]]:
    """Calculate keyword match score between description and account name.
    
    Args:
        description: Expense description
        account_name: Account name to match against
        
    Returns:
        Tuple of (score, matched_keywords)
    """
    desc_keywords = set(_extract_keywords(description))
    account_keywords = set(_extract_keywords(account_name))
    
    matched_keywords: List[str] = []
    score = 0.0
    
    # Direct keyword matches
    direct_matches = desc_keywords & account_keywords
    if direct_matches:
        matched_keywords.extend(direct_matches)
        score += len(direct_matches) * 0.3
    
    # Check against expense keyword categories
    for category, keywords in EXPENSE_KEYWORDS.items():
        category_keywords = set(keywords)
        
        # Check if description matches this category
        desc_category_matches = desc_keywords & category_keywords
        
        # Check if account name matches this category
        account_category_matches = account_keywords & category_keywords
        
        # If both match the same category, boost score
        if desc_category_matches and account_category_matches:
            matched_keywords.extend(desc_category_matches)
            score += 0.2
        
        # If account name contains the category name and description matches keywords
        if category in account_name.lower() and desc_category_matches:
            matched_keywords.append(category)
            score += 0.15
    
    # Fuzzy string similarity as fallback
    similarity = SequenceMatcher(
        None,
        _normalize_for_matching(description),
        _normalize_for_matching(account_name),
    ).ratio()
    score += similarity * 0.2
    
    # Normalize score to 0-1 range
    score = min(score, 1.0)
    
    return score, list(set(matched_keywords))


def _fuzzy_match_score(str1: str, str2: str) -> float:
    """Calculate fuzzy match score between two strings.
    
    Uses multiple matching strategies:
    1. Exact match (case-insensitive)
    2. Sequence matching ratio
    3. Token-based matching
    
    Args:
        str1: First string
        str2: Second string
        
    Returns:
        Match score between 0.0 and 1.0
    """
    # Normalize strings
    norm1 = _normalize_for_matching(str1)
    norm2 = _normalize_for_matching(str2)
    
    # Exact match
    if norm1 == norm2:
        return 1.0
    
    # One contains the other
    if norm1 in norm2 or norm2 in norm1:
        return 0.9
    
    # Sequence matching
    seq_ratio = SequenceMatcher(None, norm1, norm2).ratio()
    
    # Token-based matching
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())
    
    if tokens1 and tokens2:
        common_tokens = tokens1 & tokens2
        token_ratio = len(common_tokens) / max(len(tokens1), len(tokens2))
    else:
        token_ratio = 0.0
    
    # Combine scores with weights
    combined_score = (seq_ratio * 0.6) + (token_ratio * 0.4)
    
    return combined_score


@tool
async def extract_document_data(
    image_data: bytes,
    document_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract text and structured data from document image using chandra_ocr.
    
    Processes a document image through OCR to extract text content. The extracted
    text is normalized (full-width to half-width character conversion) for
    consistent processing.
    
    Args:
        image_data: Raw image bytes (PNG, JPG, JPEG, or PDF)
        document_hint: Optional hint about document type (e.g., "receipt", "invoice")
        
    Returns:
        Dictionary containing:
        - text: Raw extracted text
        - normalized_text: Normalized text (full-width to half-width)
        - pages: Number of pages processed
        - success: Whether extraction was successful
        - error: Error message if extraction failed
        
    Raises:
        OCRError: If OCR processing fails
    """
    logger.info(f"Extracting document data, hint={document_hint}")
    
    try:
        context = get_tool_context()
        ocr_service = context.get_ocr_service()
        
        # Determine if this is a PDF based on magic bytes
        is_pdf = image_data[:4] == b'%PDF'
        
        if is_pdf:
            result = await ocr_service.extract_from_pdf(image_data)
        else:
            result = await ocr_service.extract_text(image_data)
        
        response = {
            "text": result.text,
            "normalized_text": result.text,  # Already normalized by OCRService
            "pages": result.pages,
            "success": result.success,
            "error": result.error,
        }
        
        if result.success:
            logger.info(
                f"Successfully extracted {len(result.text)} characters "
                f"from {result.pages} page(s)"
            )
        else:
            logger.warning(f"OCR extraction failed: {result.error}")
        
        return response
        
    except OCRError as e:
        logger.error(f"OCR error extracting document data: {e}")
        return {
            "text": "",
            "normalized_text": "",
            "pages": 0,
            "success": False,
            "error": str(e),
        }
    except Exception as e:
        logger.error(f"Unexpected error extracting document data: {e}")
        return {
            "text": "",
            "normalized_text": "",
            "pages": 0,
            "success": False,
            "error": f"Unexpected error: {e}",
        }


@tool
def categorize_expense(
    description: str,
    amount: float,
    accounts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Match expense description to most appropriate expense account.
    
    Uses semantic/keyword matching to find the best matching expense account
    from the provided list. The matching considers:
    - Direct keyword matches between description and account name
    - Category-based matching using common expense keywords
    - Fuzzy string similarity
    
    Args:
        description: Expense description from the document
        amount: Expense amount (used for context, not matching)
        accounts: List of account dictionaries with keys: key, name, code
        
    Returns:
        Dictionary containing:
        - key: Account key/UUID
        - name: Account name
        - code: Account code (if available)
        - score: Match confidence score (0.0 to 1.0)
        - matched_keywords: Keywords that contributed to the match
        
    Note:
        If no accounts are provided or no match is found above threshold,
        returns a result with score 0.0 and empty key.
    """
    logger.info(f"Categorizing expense: '{description}' (amount: {amount})")
    
    if not accounts:
        logger.warning("No accounts provided for categorization")
        return {
            "key": "",
            "name": "",
            "code": None,
            "score": 0.0,
            "matched_keywords": [],
        }
    
    if not description or not description.strip():
        logger.warning("Empty description provided for categorization")
        return {
            "key": accounts[0].get("key", ""),
            "name": accounts[0].get("name", ""),
            "code": accounts[0].get("code"),
            "score": 0.0,
            "matched_keywords": [],
        }
    
    best_match: Optional[Dict[str, Any]] = None
    best_score = 0.0
    best_keywords: List[str] = []
    
    for account in accounts:
        account_name = account.get("name", "")
        if not account_name:
            continue
        
        score, keywords = _calculate_keyword_score(description, account_name)
        
        if score > best_score:
            best_score = score
            best_keywords = keywords
            best_match = account
    
    if best_match is None:
        # Return first account as fallback with zero score
        best_match = accounts[0]
        best_score = 0.0
        best_keywords = []
    
    result = {
        "key": best_match.get("key", ""),
        "name": best_match.get("name", ""),
        "code": best_match.get("code"),
        "score": round(best_score, 3),
        "matched_keywords": best_keywords,
    }
    
    logger.info(
        f"Categorized expense to '{result['name']}' "
        f"with score {result['score']:.3f}, keywords: {result['matched_keywords']}"
    )
    
    return result


@tool
def identify_supplier(
    vendor_name: str,
    suppliers: List[Dict[str, Any]],
    threshold: float = 0.6,
) -> Dict[str, Any]:
    """Match vendor name from document to existing supplier.
    
    Uses fuzzy string matching to find the best matching supplier from the
    provided list. The matching considers:
    - Exact matches (case-insensitive)
    - Substring containment
    - Sequence similarity
    - Token-based matching
    
    Args:
        vendor_name: Vendor name extracted from the document
        suppliers: List of supplier dictionaries with keys: key, name
        threshold: Minimum score threshold for a match (default: 0.6)
        
    Returns:
        Dictionary containing:
        - key: Supplier key/UUID
        - name: Supplier name
        - score: Match confidence score (0.0 to 1.0)
        - matched: Whether a match was found above threshold
        
    Note:
        If no suppliers are provided or no match is found above threshold,
        returns a result with matched=False.
    """
    logger.info(f"Identifying supplier: '{vendor_name}'")
    
    if not suppliers:
        logger.warning("No suppliers provided for identification")
        return {
            "key": "",
            "name": "",
            "score": 0.0,
            "matched": False,
        }
    
    if not vendor_name or not vendor_name.strip():
        logger.warning("Empty vendor name provided for identification")
        return {
            "key": "",
            "name": "",
            "score": 0.0,
            "matched": False,
        }
    
    best_match: Optional[Dict[str, Any]] = None
    best_score = 0.0
    
    for supplier in suppliers:
        supplier_name = supplier.get("name", "")
        if not supplier_name:
            continue
        
        score = _fuzzy_match_score(vendor_name, supplier_name)
        
        if score > best_score:
            best_score = score
            best_match = supplier
    
    # Check if best match meets threshold
    if best_match is not None and best_score >= threshold:
        result = {
            "key": best_match.get("key", ""),
            "name": best_match.get("name", ""),
            "score": round(best_score, 3),
            "matched": True,
        }
        logger.info(
            f"Identified supplier '{result['name']}' "
            f"with score {result['score']:.3f}"
        )
    else:
        result = {
            "key": "",
            "name": "",
            "score": round(best_score, 3) if best_score > 0 else 0.0,
            "matched": False,
        }
        logger.info(
            f"No supplier match found above threshold {threshold} "
            f"(best score: {best_score:.3f})"
        )
    
    return result


# =============================================================================
# Submission Tools
# =============================================================================


class ExpenseClaimLine(BaseModel):
    """A single line item in an expense claim."""
    
    date: str = Field(description="Date of expense in YYYY-MM-DD format")
    description: str = Field(description="Description of the expense")
    amount: float = Field(description="Expense amount")
    account_key: str = Field(description="Expense account key/UUID")


class ExpenseClaimData(BaseModel):
    """Data for creating an expense claim in Manager.io."""
    
    paidby: str = Field(description="Who paid for the expense (employee name or key)")
    lines: List[ExpenseClaimLine] = Field(description="Line items for the expense claim")
    description: Optional[str] = Field(default=None, description="Overall description")
    reference: Optional[str] = Field(default=None, description="Reference number")


class PurchaseInvoiceLine(BaseModel):
    """A single line item in a purchase invoice."""
    
    description: str = Field(description="Description of the item/service")
    amount: float = Field(description="Line amount")
    account_key: str = Field(description="Expense/asset account key")
    qty: float = Field(default=1.0, description="Quantity")


class PurchaseInvoiceData(BaseModel):
    """Data for creating a purchase invoice in Manager.io."""
    
    supplier_key: str = Field(description="Supplier key/UUID")
    issue_date: str = Field(description="Invoice date in YYYY-MM-DD format")
    due_date: Optional[str] = Field(default=None, description="Due date in YYYY-MM-DD format")
    lines: List[PurchaseInvoiceLine] = Field(description="Line items")
    reference: Optional[str] = Field(default=None, description="Invoice reference/number")
    description: Optional[str] = Field(default=None, description="Overall description")


class SubmissionResult(BaseModel):
    """Result of a submission to Manager.io."""
    
    success: bool = Field(description="Whether submission was successful")
    key: Optional[str] = Field(default=None, description="Created entry key if successful")
    message: str = Field(description="Success or error message")
    entry_type: str = Field(description="Type of entry created")


@tool
async def create_expense_claim(
    company_id: str,
    user_id: str,
    date: str,
    paidby: str,
    payee: str,
    description: str,
    lines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Create an expense claim in Manager.io.
    
    Submits an expense claim with one or more line items. Each line represents
    a separate expense that was paid by the claimant.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        date: Date of the expense claim in YYYY-MM-DD format
        paidby: Who paid for the expense (employee key/UUID)
        payee: Name of the payee/vendor
        description: Overall description for the claim
        lines: List of line items, each with: account_key, line_description, qty, amount
        
    Returns:
        Dictionary containing:
        - success: Whether submission was successful
        - key: Created entry key if successful
        - message: Success or error message
        - entry_type: "expense_claim"
        
    Raises:
        CompanyNotFoundError: If company not found or access denied
        ManagerIOError: If the Manager.io API request fails
    """
    from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine
    
    logger.info(f"Creating expense claim for company {company_id}, {len(lines)} lines")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        # Build the expense claim line items
        claim_lines = []
        for line in lines:
            claim_line = ExpenseClaimLine(
                account=line.get("account_key", ""),
                line_description=line.get("line_description", line.get("description", "")),
                qty=int(line.get("qty", 1)),
                purchase_unit_price=float(line.get("amount", line.get("purchase_unit_price", 0))),
            )
            claim_lines.append(claim_line)
        
        # Create the expense claim data model
        expense_data = ExpenseClaimData(
            date=date,
            paid_by=paidby,
            payee=payee,
            description=description,
            lines=claim_lines,
            has_line_description=True,
        )
        
        # Submit to Manager.io
        result = await client.create_expense_claim(expense_data)
        
        logger.info(f"Successfully created expense claim: {result.key}")
        
        return {
            "success": result.success,
            "key": result.key,
            "message": result.message or "Expense claim created successfully",
            "entry_type": "expense_claim",
        }
        
    except CompanyNotFoundError:
        logger.error(f"Company not found: {company_id}")
        return {
            "success": False,
            "key": None,
            "message": f"Company not found: {company_id}",
            "entry_type": "expense_claim",
        }
    except ManagerIOError as e:
        logger.error(f"Manager.io API error creating expense claim: {e}")
        return {
            "success": False,
            "key": None,
            "message": f"Manager.io API error: {e}",
            "entry_type": "expense_claim",
        }
    except Exception as e:
        logger.error(f"Unexpected error creating expense claim: {e}")
        return {
            "success": False,
            "key": None,
            "message": f"Unexpected error: {e}",
            "entry_type": "expense_claim",
        }


@tool
async def create_purchase_invoice(
    company_id: str,
    user_id: str,
    supplier_key: str,
    issue_date: str,
    reference: str,
    description: str,
    lines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Create a purchase invoice in Manager.io.
    
    Submits a purchase invoice for goods or services received from a supplier.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        supplier_key: Supplier key/UUID
        issue_date: Invoice date in YYYY-MM-DD format
        reference: Invoice reference/number
        description: Overall description
        lines: List of line items, each with: account_key, line_description, amount
        
    Returns:
        Dictionary containing:
        - success: Whether submission was successful
        - key: Created entry key if successful
        - message: Success or error message
        - entry_type: "purchase_invoice"
        
    Raises:
        CompanyNotFoundError: If company not found or access denied
        ManagerIOError: If the Manager.io API request fails
    """
    from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine
    
    logger.info(f"Creating purchase invoice for company {company_id}, supplier {supplier_key}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        # Build the purchase invoice line items
        invoice_lines = []
        for line in lines:
            invoice_line = PurchaseInvoiceLine(
                account=line.get("account_key", ""),
                line_description=line.get("line_description", line.get("description", "")),
                purchase_unit_price=float(line.get("amount", line.get("purchase_unit_price", 0))),
            )
            invoice_lines.append(invoice_line)
        
        # Create the purchase invoice data model
        invoice_data = PurchaseInvoiceData(
            issue_date=issue_date,
            reference=reference,
            description=description,
            supplier=supplier_key,
            lines=invoice_lines,
            has_line_number=True,
            has_line_description=True,
        )
        
        # Submit to Manager.io
        result = await client.create_purchase_invoice(invoice_data)
        
        logger.info(f"Successfully created purchase invoice: {result.key}")
        
        return {
            "success": result.success,
            "key": result.key,
            "message": result.message or "Purchase invoice created successfully",
            "entry_type": "purchase_invoice",
        }
        
    except CompanyNotFoundError:
        logger.error(f"Company not found: {company_id}")
        return {
            "success": False,
            "key": None,
            "message": f"Company not found: {company_id}",
            "entry_type": "purchase_invoice",
        }
    except ManagerIOError as e:
        logger.error(f"Manager.io API error creating purchase invoice: {e}")
        return {
            "success": False,
            "key": None,
            "message": f"Manager.io API error: {e}",
            "entry_type": "purchase_invoice",
        }
    except Exception as e:
        logger.error(f"Unexpected error creating purchase invoice: {e}")
        return {
            "success": False,
            "key": None,
            "message": f"Unexpected error: {e}",
            "entry_type": "purchase_invoice",
        }


@tool
async def amend_entry(
    company_id: str,
    user_id: str,
    entry_key: str,
    entry_type: str,
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """Amend an existing entry in Manager.io.
    
    Updates an existing expense claim or purchase invoice with new data.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        entry_key: The key of the entry to amend
        entry_type: Type of entry ("expense_claim" or "purchase_invoice")
        updates: Dictionary of fields to update in Manager.io API format
        
    Returns:
        Dictionary containing:
        - success: Whether amendment was successful
        - key: Entry key
        - message: Success or error message
        - entry_type: Type of entry amended
        
    Raises:
        CompanyNotFoundError: If company not found or access denied
        ManagerIOError: If the Manager.io API request fails
    """
    logger.info(f"Amending {entry_type} {entry_key} for company {company_id}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        # Map entry type to Manager.io endpoint type
        if entry_type == "expense_claim":
            api_entry_type = "expense-claim-form"
        elif entry_type == "purchase_invoice":
            api_entry_type = "purchase-invoice-form"
        else:
            return {
                "success": False,
                "key": entry_key,
                "message": f"Unknown entry type: {entry_type}",
                "entry_type": entry_type,
            }
        
        # Use the client's update_entry method
        result = await client.update_entry(api_entry_type, entry_key, updates)
        
        logger.info(f"Successfully amended {entry_type}: {entry_key}")
        
        return {
            "success": result.success,
            "key": entry_key,
            "message": result.message or f"{entry_type.replace('_', ' ').title()} amended successfully",
            "entry_type": entry_type,
        }
        
    except CompanyNotFoundError:
        logger.error(f"Company not found: {company_id}")
        return {
            "success": False,
            "key": entry_key,
            "message": f"Company not found: {company_id}",
            "entry_type": entry_type,
        }
    except ManagerIOError as e:
        logger.error(f"Manager.io API error amending entry: {e}")
        return {
            "success": False,
            "key": entry_key,
            "message": f"Manager.io API error: {e}",
            "entry_type": entry_type,
        }
    except Exception as e:
        logger.error(f"Unexpected error amending entry: {e}")
        return {
            "success": False,
            "key": entry_key,
            "message": f"Unexpected error: {e}",
            "entry_type": entry_type,
        }


@tool
def handle_forex(
    amount: float,
    from_currency: str,
    to_currency: str,
    exchange_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """Handle foreign exchange conversion for multi-currency transactions.
    
    Converts an amount from one currency to another using the provided
    exchange rate. If no rate is provided, returns the amount unchanged
    with a note that manual rate entry is required.
    
    Args:
        amount: Amount to convert
        from_currency: Source currency code (e.g., "USD", "EUR")
        to_currency: Target currency code
        exchange_rate: Optional exchange rate (from_currency to to_currency)
        
    Returns:
        Dictionary containing:
        - original_amount: Original amount
        - original_currency: Original currency code
        - converted_amount: Converted amount (or original if no rate)
        - target_currency: Target currency code
        - exchange_rate: Exchange rate used (or None)
        - rate_source: Source of the exchange rate
        - needs_manual_rate: Whether manual rate entry is required
    """
    logger.info(f"Handling forex: {amount} {from_currency} -> {to_currency}")
    
    # Normalize currency codes
    from_currency = from_currency.upper().strip()
    to_currency = to_currency.upper().strip()
    
    # Same currency - no conversion needed
    if from_currency == to_currency:
        return {
            "original_amount": amount,
            "original_currency": from_currency,
            "converted_amount": amount,
            "target_currency": to_currency,
            "exchange_rate": 1.0,
            "rate_source": "same_currency",
            "needs_manual_rate": False,
        }
    
    # If exchange rate provided, use it
    if exchange_rate is not None and exchange_rate > 0:
        converted_amount = round(amount * exchange_rate, 2)
        return {
            "original_amount": amount,
            "original_currency": from_currency,
            "converted_amount": converted_amount,
            "target_currency": to_currency,
            "exchange_rate": exchange_rate,
            "rate_source": "provided",
            "needs_manual_rate": False,
        }
    
    # No exchange rate - return original with flag for manual entry
    logger.warning(f"No exchange rate provided for {from_currency} -> {to_currency}")
    return {
        "original_amount": amount,
        "original_currency": from_currency,
        "converted_amount": amount,  # Return original amount
        "target_currency": to_currency,
        "exchange_rate": None,
        "rate_source": "none",
        "needs_manual_rate": True,
    }


# =============================================================================
# Additional Transaction Tools
# =============================================================================


@tool
async def create_payment(
    company_id: str,
    user_id: str,
    date: str,
    paid_from: str,
    payee: str,
    description: str,
    lines: List[Dict[str, Any]],
    reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a payment in Manager.io.
    
    Records a payment made from a bank or cash account.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        date: Payment date in YYYY-MM-DD format
        paid_from: Bank/cash account key to pay from
        payee: Name of the payee
        description: Payment description
        lines: List of line items, each with: account_key, line_description, amount
        reference: Optional reference number
        
    Returns:
        Dictionary with success status, key, message, and entry_type
    """
    from app.services.manager_io import PaymentData, PaymentLine
    
    logger.info(f"Creating payment for company {company_id}, {len(lines)} lines")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        payment_lines = [
            PaymentLine(
                account=line.get("account_key", ""),
                line_description=line.get("line_description", line.get("description", "")),
                amount=float(line.get("amount", 0)),
            )
            for line in lines
        ]
        
        payment_data = PaymentData(
            date=date,
            paid_from=paid_from,
            payee=payee,
            description=description,
            lines=payment_lines,
            reference=reference,
            has_line_description=True,
        )
        
        result = await client.create_payment(payment_data)
        return {"success": result.success, "key": result.key, "message": result.message, "entry_type": "payment"}
        
    except CompanyNotFoundError:
        return {"success": False, "key": None, "message": f"Company not found: {company_id}", "entry_type": "payment"}
    except ManagerIOError as e:
        return {"success": False, "key": None, "message": f"Manager.io API error: {e}", "entry_type": "payment"}
    except Exception as e:
        return {"success": False, "key": None, "message": f"Unexpected error: {e}", "entry_type": "payment"}


@tool
async def create_receipt(
    company_id: str,
    user_id: str,
    date: str,
    received_in: str,
    payer: str,
    description: str,
    lines: List[Dict[str, Any]],
    reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a receipt in Manager.io.
    
    Records money received into a bank or cash account.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        date: Receipt date in YYYY-MM-DD format
        received_in: Bank/cash account key to receive into
        payer: Name of the payer
        description: Receipt description
        lines: List of line items, each with: account_key, line_description, amount
        reference: Optional reference number
        
    Returns:
        Dictionary with success status, key, message, and entry_type
    """
    from app.services.manager_io import ReceiptData, ReceiptLine
    
    logger.info(f"Creating receipt for company {company_id}, {len(lines)} lines")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        receipt_lines = [
            ReceiptLine(
                account=line.get("account_key", ""),
                line_description=line.get("line_description", line.get("description", "")),
                amount=float(line.get("amount", 0)),
            )
            for line in lines
        ]
        
        receipt_data = ReceiptData(
            date=date,
            received_in=received_in,
            payer=payer,
            description=description,
            lines=receipt_lines,
            reference=reference,
            has_line_description=True,
        )
        
        result = await client.create_receipt(receipt_data)
        return {"success": result.success, "key": result.key, "message": result.message, "entry_type": "receipt"}
        
    except CompanyNotFoundError:
        return {"success": False, "key": None, "message": f"Company not found: {company_id}", "entry_type": "receipt"}
    except ManagerIOError as e:
        return {"success": False, "key": None, "message": f"Manager.io API error: {e}", "entry_type": "receipt"}
    except Exception as e:
        return {"success": False, "key": None, "message": f"Unexpected error: {e}", "entry_type": "receipt"}


@tool
async def create_sales_invoice(
    company_id: str,
    user_id: str,
    customer_key: str,
    issue_date: str,
    reference: str,
    description: str,
    lines: List[Dict[str, Any]],
    due_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a sales invoice in Manager.io.
    
    Creates an invoice for goods or services sold to a customer.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        customer_key: Customer key/UUID
        issue_date: Invoice date in YYYY-MM-DD format
        reference: Invoice reference/number
        description: Overall description
        lines: List of line items, each with: account_key, line_description, qty, amount
        due_date: Optional due date in YYYY-MM-DD format
        
    Returns:
        Dictionary with success status, key, message, and entry_type
    """
    from app.services.manager_io import SalesInvoiceData, SalesInvoiceLine
    
    logger.info(f"Creating sales invoice for company {company_id}, customer {customer_key}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        invoice_lines = [
            SalesInvoiceLine(
                account=line.get("account_key", ""),
                line_description=line.get("line_description", line.get("description", "")),
                qty=int(line.get("qty", 1)),
                sales_unit_price=float(line.get("amount", line.get("sales_unit_price", 0))),
            )
            for line in lines
        ]
        
        invoice_data = SalesInvoiceData(
            issue_date=issue_date,
            due_date=due_date,
            reference=reference,
            description=description,
            customer=customer_key,
            lines=invoice_lines,
            has_line_number=True,
            has_line_description=True,
        )
        
        result = await client.create_sales_invoice(invoice_data)
        return {"success": result.success, "key": result.key, "message": result.message, "entry_type": "sales_invoice"}
        
    except CompanyNotFoundError:
        return {"success": False, "key": None, "message": f"Company not found: {company_id}", "entry_type": "sales_invoice"}
    except ManagerIOError as e:
        return {"success": False, "key": None, "message": f"Manager.io API error: {e}", "entry_type": "sales_invoice"}
    except Exception as e:
        return {"success": False, "key": None, "message": f"Unexpected error: {e}", "entry_type": "sales_invoice"}


@tool
async def create_journal_entry(
    company_id: str,
    user_id: str,
    date: str,
    narration: str,
    lines: List[Dict[str, Any]],
    reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a journal entry in Manager.io.
    
    Creates a manual journal entry with debit and credit lines. Debits must equal credits.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        date: Entry date in YYYY-MM-DD format
        narration: Description/memo for the journal entry
        lines: List of line items, each with: account_key, debit (or credit), line_description
        reference: Optional reference number
        
    Returns:
        Dictionary with success status, key, message, and entry_type
    """
    from app.services.manager_io import JournalEntryData, JournalEntryLine
    
    logger.info(f"Creating journal entry for company {company_id}, {len(lines)} lines")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        entry_lines = [
            JournalEntryLine(
                account=line.get("account_key", ""),
                debit=float(line["debit"]) if line.get("debit") is not None else None,
                credit=float(line["credit"]) if line.get("credit") is not None else None,
                line_description=line.get("line_description", line.get("description")),
            )
            for line in lines
        ]
        
        entry_data = JournalEntryData(
            date=date,
            narration=narration,
            lines=entry_lines,
            reference=reference,
        )
        
        result = await client.create_journal_entry(entry_data)
        return {"success": result.success, "key": result.key, "message": result.message, "entry_type": "journal_entry"}
        
    except CompanyNotFoundError:
        return {"success": False, "key": None, "message": f"Company not found: {company_id}", "entry_type": "journal_entry"}
    except ManagerIOError as e:
        return {"success": False, "key": None, "message": f"Manager.io API error: {e}", "entry_type": "journal_entry"}
    except Exception as e:
        return {"success": False, "key": None, "message": f"Unexpected error: {e}", "entry_type": "journal_entry"}


@tool
async def create_transfer(
    company_id: str,
    user_id: str,
    date: str,
    paid_from: str,
    received_in: str,
    amount: float,
    description: Optional[str] = None,
    reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an inter-account transfer in Manager.io.
    
    Transfers money between bank/cash accounts.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        date: Transfer date in YYYY-MM-DD format
        paid_from: Source bank/cash account key
        received_in: Destination bank/cash account key
        amount: Transfer amount
        description: Optional description
        reference: Optional reference number
        
    Returns:
        Dictionary with success status, key, message, and entry_type
    """
    from app.services.manager_io import InterAccountTransferData
    
    logger.info(f"Creating transfer for company {company_id}, amount {amount}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        transfer_data = InterAccountTransferData(
            date=date,
            paid_from=paid_from,
            received_in=received_in,
            amount=amount,
            description=description,
            reference=reference,
        )
        
        result = await client.create_transfer(transfer_data)
        return {"success": result.success, "key": result.key, "message": result.message, "entry_type": "transfer"}
        
    except CompanyNotFoundError:
        return {"success": False, "key": None, "message": f"Company not found: {company_id}", "entry_type": "transfer"}
    except ManagerIOError as e:
        return {"success": False, "key": None, "message": f"Manager.io API error: {e}", "entry_type": "transfer"}
    except Exception as e:
        return {"success": False, "key": None, "message": f"Unexpected error: {e}", "entry_type": "transfer"}


@tool
async def delete_entry(
    company_id: str,
    user_id: str,
    entry_key: str,
    entry_type: str,
) -> Dict[str, Any]:
    """Delete an entry from Manager.io.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        entry_key: The key of the entry to delete
        entry_type: Type of entry (expense_claim, purchase_invoice, sales_invoice, 
                    payment, receipt, journal_entry, transfer)
        
    Returns:
        Dictionary with success status and message
    """
    logger.info(f"Deleting {entry_type} {entry_key} for company {company_id}")
    
    type_mapping = {
        "expense_claim": "expense-claim-form",
        "purchase_invoice": "purchase-invoice-form",
        "sales_invoice": "sales-invoice-form",
        "payment": "payment-form",
        "receipt": "receipt-form",
        "journal_entry": "journal-entry-form",
        "transfer": "inter-account-transfer-form",
    }
    
    api_entry_type = type_mapping.get(entry_type)
    if not api_entry_type:
        return {"success": False, "message": f"Unknown entry type: {entry_type}"}
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        result = await client.delete_entry(api_entry_type, entry_key)
        return {"success": result.success, "message": result.message}
    except CompanyNotFoundError:
        return {"success": False, "message": f"Company not found: {company_id}"}
    except ManagerIOError as e:
        return {"success": False, "message": f"Manager.io API error: {e}"}
    except Exception as e:
        return {"success": False, "message": f"Unexpected error: {e}"}


# =============================================================================
# Report Tools
# =============================================================================


@tool
async def get_balance_sheet(
    company_id: str,
    user_id: str,
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch balance sheet report from Manager.io.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        as_of_date: Optional date in YYYY-MM-DD format (defaults to today)
        
    Returns:
        Balance sheet data including assets, liabilities, and equity
    """
    logger.info(f"Fetching balance sheet for company {company_id}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        data = await client.get_balance_sheet(as_of_date)
        return {"success": True, "report_type": "balance_sheet", "as_of_date": as_of_date, "data": data}
    except CompanyNotFoundError:
        return {"success": False, "report_type": "balance_sheet", "message": f"Company not found: {company_id}"}
    except ManagerIOError as e:
        return {"success": False, "report_type": "balance_sheet", "message": f"Manager.io API error: {e}"}
    except Exception as e:
        return {"success": False, "report_type": "balance_sheet", "message": f"Unexpected error: {e}"}


@tool
async def get_profit_and_loss(
    company_id: str,
    user_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch profit and loss (income statement) report from Manager.io.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        from_date: Start date in YYYY-MM-DD format
        to_date: End date in YYYY-MM-DD format
        
    Returns:
        Profit and loss data including income, expenses, and net profit
    """
    logger.info(f"Fetching P&L for company {company_id}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        data = await client.get_profit_and_loss(from_date, to_date)
        return {"success": True, "report_type": "profit_and_loss", "from_date": from_date, "to_date": to_date, "data": data}
    except CompanyNotFoundError:
        return {"success": False, "report_type": "profit_and_loss", "message": f"Company not found: {company_id}"}
    except ManagerIOError as e:
        return {"success": False, "report_type": "profit_and_loss", "message": f"Manager.io API error: {e}"}
    except Exception as e:
        return {"success": False, "report_type": "profit_and_loss", "message": f"Unexpected error: {e}"}


@tool
async def get_trial_balance(
    company_id: str,
    user_id: str,
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch trial balance from Manager.io.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        as_of_date: Optional date in YYYY-MM-DD format
        
    Returns:
        Trial balance data with debit and credit totals
    """
    logger.info(f"Fetching trial balance for company {company_id}")
    
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        data = await client.get_trial_balance(as_of_date)
        return {"success": True, "report_type": "trial_balance", "as_of_date": as_of_date, "data": data}
    except CompanyNotFoundError:
        return {"success": False, "report_type": "trial_balance", "message": f"Company not found: {company_id}"}
    except ManagerIOError as e:
        return {"success": False, "report_type": "trial_balance", "message": f"Manager.io API error: {e}"}
    except Exception as e:
        return {"success": False, "report_type": "trial_balance", "message": f"Unexpected error: {e}"}


@tool
async def get_aged_receivables(company_id: str, user_id: str) -> Dict[str, Any]:
    """Fetch aged receivables report from Manager.io. Shows outstanding customer invoices by age."""
    logger.info(f"Fetching aged receivables for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        data = await client.get_aged_receivables()
        return {"success": True, "report_type": "aged_receivables", "data": data}
    except (CompanyNotFoundError, ManagerIOError, Exception) as e:
        return {"success": False, "report_type": "aged_receivables", "message": str(e)}


@tool
async def get_aged_payables(company_id: str, user_id: str) -> Dict[str, Any]:
    """Fetch aged payables report from Manager.io. Shows outstanding supplier invoices by age."""
    logger.info(f"Fetching aged payables for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        data = await client.get_aged_payables()
        return {"success": True, "report_type": "aged_payables", "data": data}
    except (CompanyNotFoundError, ManagerIOError, Exception) as e:
        return {"success": False, "report_type": "aged_payables", "message": str(e)}


# =============================================================================
# Bank Account & Reference Data Tools
# =============================================================================


@tool
async def get_bank_accounts(company_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetch bank and cash accounts from Manager.io with their current balances."""
    logger.info(f"Fetching bank accounts for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        accounts = await client.get_bank_accounts()
        return [{"key": a.get("Key", a.get("key", "")), 
                 "name": a.get("Name", a.get("name", "")), 
                 "balance": a.get("Balance", a.get("balance", 0)),
                 "currency": a.get("Currency", a.get("currency", "USD"))} 
                for a in accounts]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching bank accounts: {e}")
        raise


@tool
async def get_employees(company_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetch employees from Manager.io. Useful for expense claims where you need to specify who paid."""
    logger.info(f"Fetching employees for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        employees = await client.get_employees()
        return [{"key": e.get("Key", e.get("key", "")), "name": e.get("Name", e.get("name", ""))} for e in employees]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching employees: {e}")
        raise


@tool
async def get_credit_notes(
    company_id: str,
    user_id: str,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch credit notes from Manager.io.
    
    Credit notes are used to reduce amounts owed by customers (sales credit notes)
    or amounts owed to suppliers (purchase credit notes).
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        limit: Maximum number of records to return
        
    Returns:
        List of credit note dictionaries
    """
    logger.info(f"Fetching credit notes for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        response = await client.get_credit_notes(skip=0, take=limit)
        return [
            {
                "key": item.get("Key", item.get("key", "")),
                "date": item.get("Date", item.get("date", "")),
                "reference": item.get("Reference", item.get("reference", "")),
                "customer": item.get("Customer", item.get("customer", "")),
                "sales_invoice": item.get("SalesInvoice", item.get("sales_invoice", "")),
                "description": item.get("Description", item.get("description", "")),
                "amount": float(item.get("Amount", item.get("amount", 0)) or 0),
            }
            for item in response.items
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching credit notes: {e}")
        raise


# =============================================================================
# Inventory Tools
# =============================================================================


@tool
async def get_inventory_items(company_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetch inventory items from Manager.io.
    
    Returns inventory items with stock levels, costs, and pricing information.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        
    Returns:
        List of inventory item dictionaries with fields:
        - key, item_code, item_name, qty_on_hand, qty_available
        - average_cost, total_cost, sale_price, purchase_price
    """
    logger.info(f"Fetching inventory items for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        items = await client.get_inventory_items()
        return [
            {
                "key": item.get("Key", item.get("key", "")),
                "item_code": item.get("ItemCode", item.get("item_code", "")),
                "item_name": item.get("ItemName", item.get("item_name", "")),
                "description": item.get("Description", item.get("description", "")),
                "unit_name": item.get("UnitName", item.get("unit_name", "")),
                "qty_on_hand": float(item.get("QtyOnHand", item.get("qty_on_hand", 0)) or 0),
                "qty_available": float(item.get("QtyAvailable", item.get("qty_available", 0)) or 0),
                "qty_reserved": float(item.get("QtyReserved", item.get("qty_reserved", 0)) or 0),
                "average_cost": float(item.get("AverageCost", item.get("average_cost", 0)) or 0),
                "total_cost": float(item.get("TotalCost", item.get("total_cost", 0)) or 0),
                "sale_price": float(item.get("SalePrice", item.get("sale_price", 0)) or 0),
                "purchase_price": float(item.get("PurchasePrice", item.get("purchase_price", 0)) or 0),
            }
            for item in items
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching inventory items: {e}")
        raise


@tool
async def get_inventory_kits(company_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetch inventory kits from Manager.io.
    
    Inventory kits are bundles of inventory items sold together.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        
    Returns:
        List of inventory kit dictionaries
    """
    logger.info(f"Fetching inventory kits for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        kits = await client.get_inventory_kits()
        return [
            {
                "key": kit.get("Key", kit.get("key", "")),
                "item_code": kit.get("ItemCode", kit.get("item_code", "")),
                "item_name": kit.get("ItemName", kit.get("item_name", "")),
                "unit_name": kit.get("UnitName", kit.get("unit_name", "")),
                "sales_price": float(kit.get("SalesPrice", kit.get("sales_price", 0)) or 0),
            }
            for kit in kits
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching inventory kits: {e}")
        raise


@tool
async def get_debit_notes(company_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch debit notes from Manager.io.
    
    Debit notes reduce amounts owed to suppliers (e.g., for returns or adjustments).
    """
    logger.info(f"Fetching debit notes for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        response = await client.get_debit_notes(skip=0, take=limit)
        return [
            {
                "key": item.get("Key", item.get("key", "")),
                "date": item.get("Date", item.get("date", "")),
                "reference": item.get("Reference", item.get("reference", "")),
                "supplier": item.get("Supplier", item.get("supplier", "")),
                "purchase_invoice": item.get("PurchaseInvoice", item.get("purchase_invoice", "")),
                "description": item.get("Description", item.get("description", "")),
                "amount": float(item.get("Amount", item.get("amount", 0)) or 0),
            }
            for item in response.items
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching debit notes: {e}")
        raise


@tool
async def get_sales_invoices(company_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch sales invoices from Manager.io.
    
    Returns list of sales invoices with status, amounts, and due dates.
    """
    logger.info(f"Fetching sales invoices for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        response = await client.get_sales_invoices(skip=0, take=limit)
        return [
            {
                "key": item.get("Key", item.get("key", "")),
                "issue_date": item.get("IssueDate", item.get("issue_date", "")),
                "due_date": item.get("DueDate", item.get("due_date", "")),
                "reference": item.get("Reference", item.get("reference", "")),
                "customer": item.get("Customer", item.get("customer", "")),
                "description": item.get("Description", item.get("description", "")),
                "invoice_amount": float(item.get("InvoiceAmount", item.get("invoice_amount", 0)) or 0),
                "balance_due": float(item.get("BalanceDue", item.get("balance_due", 0)) or 0),
                "status": item.get("Status", item.get("status", "")),
            }
            for item in response.items
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching sales invoices: {e}")
        raise


@tool
async def get_purchase_invoices(company_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch purchase invoices from Manager.io.
    
    Returns list of purchase invoices with status, amounts, and due dates.
    """
    logger.info(f"Fetching purchase invoices for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        response = await client.get_purchase_invoices(skip=0, take=limit)
        return [
            {
                "key": item.get("Key", item.get("key", "")),
                "issue_date": item.get("IssueDate", item.get("issue_date", "")),
                "due_date": item.get("DueDate", item.get("due_date", "")),
                "reference": item.get("Reference", item.get("reference", "")),
                "supplier": item.get("Supplier", item.get("supplier", "")),
                "description": item.get("Description", item.get("description", "")),
                "invoice_amount": float(item.get("InvoiceAmount", item.get("invoice_amount", 0)) or 0),
                "balance_due": float(item.get("BalanceDue", item.get("balance_due", 0)) or 0),
                "status": item.get("Status", item.get("status", "")),
            }
            for item in response.items
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching purchase invoices: {e}")
        raise


@tool
async def get_sales_orders(company_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch sales orders from Manager.io."""
    logger.info(f"Fetching sales orders for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        response = await client.get_sales_orders(skip=0, take=limit)
        return [
            {
                "key": item.get("Key", item.get("key", "")),
                "date": item.get("Date", item.get("date", "")),
                "reference": item.get("Reference", item.get("reference", "")),
                "customer": item.get("Customer", item.get("customer", "")),
                "description": item.get("Description", item.get("description", "")),
                "order_amount": float(item.get("OrderAmount", item.get("order_amount", 0)) or 0),
                "invoice_status": item.get("InvoiceStatus", item.get("invoice_status", "")),
                "delivery_status": item.get("DeliveryStatus", item.get("delivery_status", "")),
            }
            for item in response.items
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching sales orders: {e}")
        raise


@tool
async def get_purchase_orders(company_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch purchase orders from Manager.io."""
    logger.info(f"Fetching purchase orders for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        response = await client.get_purchase_orders(skip=0, take=limit)
        return [
            {
                "key": item.get("Key", item.get("key", "")),
                "date": item.get("Date", item.get("date", "")),
                "reference": item.get("Reference", item.get("reference", "")),
                "supplier": item.get("Supplier", item.get("supplier", "")),
                "description": item.get("Description", item.get("description", "")),
                "order_amount": float(item.get("OrderAmount", item.get("order_amount", 0)) or 0),
                "invoice_status": item.get("InvoiceStatus", item.get("invoice_status", "")),
                "delivery_status": item.get("DeliveryStatus", item.get("delivery_status", "")),
            }
            for item in response.items
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching purchase orders: {e}")
        raise


@tool
async def get_goods_receipts(company_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch goods receipts from Manager.io. Records inventory received from suppliers."""
    logger.info(f"Fetching goods receipts for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        response = await client.get_goods_receipts(skip=0, take=limit)
        return [
            {
                "key": item.get("Key", item.get("key", "")),
                "date": item.get("Date", item.get("date", "")),
                "reference": item.get("Reference", item.get("reference", "")),
                "supplier": item.get("Supplier", item.get("supplier", "")),
                "description": item.get("Description", item.get("description", "")),
                "qty_received": float(item.get("QtyReceived", item.get("qty_received", 0)) or 0),
            }
            for item in response.items
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching goods receipts: {e}")
        raise


@tool
async def get_delivery_notes(company_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch delivery notes from Manager.io. Records inventory shipped to customers."""
    logger.info(f"Fetching delivery notes for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        response = await client.get_delivery_notes(skip=0, take=limit)
        return [
            {
                "key": item.get("Key", item.get("key", "")),
                "delivery_date": item.get("DeliveryDate", item.get("delivery_date", "")),
                "reference": item.get("Reference", item.get("reference", "")),
                "customer": item.get("Customer", item.get("customer", "")),
                "description": item.get("Description", item.get("description", "")),
                "qty_delivered": float(item.get("QtyDelivered", item.get("qty_delivered", 0)) or 0),
            }
            for item in response.items
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching delivery notes: {e}")
        raise


@tool
async def get_tax_codes(company_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetch tax codes from Manager.io. Used for applying correct tax rates to transactions."""
    logger.info(f"Fetching tax codes for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        codes = await client.get_tax_codes()
        return [{"key": c.get("Key", c.get("key", "")), "name": c.get("Name", c.get("name", ""))} for c in codes]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching tax codes: {e}")
        raise


@tool
async def get_fixed_assets(company_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetch fixed assets from Manager.io. Tracks property, equipment, vehicles, etc."""
    logger.info(f"Fetching fixed assets for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        assets = await client.get_fixed_assets()
        return [
            {
                "key": a.get("Key", a.get("key", "")),
                "code": a.get("Code", a.get("code", "")),
                "name": a.get("Name", a.get("name", "")),
                "description": a.get("Description", a.get("description", "")),
                "acquisition_cost": float(a.get("AcquisitionCost", a.get("acquisition_cost", 0)) or 0),
                "depreciation": float(a.get("Depreciation", a.get("depreciation", 0)) or 0),
                "book_value": float(a.get("BookValue", a.get("book_value", 0)) or 0),
                "status": a.get("Status", a.get("status", "")),
            }
            for a in assets
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching fixed assets: {e}")
        raise


@tool
async def get_projects(company_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetch projects from Manager.io. Tracks income and expenses by project."""
    logger.info(f"Fetching projects for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        projects = await client.get_projects()
        return [
            {
                "key": p.get("Key", p.get("key", "")),
                "name": p.get("Name", p.get("name", "")),
                "income": float(p.get("Income", p.get("income", 0)) or 0),
                "expenses": float(p.get("Expenses", p.get("expenses", 0)) or 0),
                "profit": float(p.get("Profit", p.get("profit", 0)) or 0),
            }
            for p in projects
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching projects: {e}")
        raise


@tool
async def create_credit_note(
    company_id: str,
    user_id: str,
    customer_key: str,
    date: str,
    lines: List[Dict[str, Any]],
    sales_invoice_key: Optional[str] = None,
    reference: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a credit note in Manager.io.
    
    Credit notes reduce amounts owed by customers (e.g., for returns or adjustments).
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        customer_key: Customer key/UUID
        date: Credit note date in YYYY-MM-DD format
        lines: List of line items, each with: account_key, line_description, amount
        sales_invoice_key: Optional sales invoice to credit against
        reference: Optional reference number
        description: Optional description
    """
    logger.info(f"Creating credit note for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        payload = {
            "Date": date,
            "Customer": customer_key,
            "Lines": [
                {"Account": l.get("account_key", ""), "LineDescription": l.get("line_description", ""),
                 "Amount": float(l.get("amount", 0))}
                for l in lines
            ],
        }
        if sales_invoice_key:
            payload["SalesInvoice"] = sales_invoice_key
        if reference:
            payload["Reference"] = reference
        if description:
            payload["Description"] = description
        
        result = await client.create_credit_note(payload)
        return {"success": result.success, "key": result.key, "message": result.message, "entry_type": "credit_note"}
    except (CompanyNotFoundError, ManagerIOError) as e:
        return {"success": False, "key": None, "message": str(e), "entry_type": "credit_note"}


@tool
async def create_debit_note(
    company_id: str,
    user_id: str,
    supplier_key: str,
    date: str,
    lines: List[Dict[str, Any]],
    purchase_invoice_key: Optional[str] = None,
    reference: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a debit note in Manager.io.
    
    Debit notes reduce amounts owed to suppliers (e.g., for returns or adjustments).
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        supplier_key: Supplier key/UUID
        date: Debit note date in YYYY-MM-DD format
        lines: List of line items, each with: account_key, line_description, amount
        purchase_invoice_key: Optional purchase invoice to debit against
        reference: Optional reference number
        description: Optional description
    """
    logger.info(f"Creating debit note for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        payload = {
            "Date": date,
            "Supplier": supplier_key,
            "Lines": [
                {"Account": l.get("account_key", ""), "LineDescription": l.get("line_description", ""),
                 "Amount": float(l.get("amount", 0))}
                for l in lines
            ],
        }
        if purchase_invoice_key:
            payload["PurchaseInvoice"] = purchase_invoice_key
        if reference:
            payload["Reference"] = reference
        if description:
            payload["Description"] = description
        
        result = await client.create_debit_note(payload)
        return {"success": result.success, "key": result.key, "message": result.message, "entry_type": "debit_note"}
    except (CompanyNotFoundError, ManagerIOError) as e:
        return {"success": False, "key": None, "message": str(e), "entry_type": "debit_note"}


# =============================================================================
# Inventory Operation Tools
# =============================================================================


@tool
async def create_goods_receipt(
    company_id: str,
    user_id: str,
    date: str,
    supplier_key: str,
    lines: List[Dict[str, Any]],
    reference: Optional[str] = None,
    description: Optional[str] = None,
    purchase_order_key: Optional[str] = None,
    inventory_location_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a goods receipt in Manager.io.
    
    Records inventory received from a supplier. Use when physically receiving goods.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        date: Receipt date in YYYY-MM-DD format
        supplier_key: Supplier key/UUID
        lines: List of line items, each with: inventory_item_key, qty
        reference: Optional reference number
        description: Optional description
        purchase_order_key: Optional purchase order this receipt is for
        inventory_location_key: Optional inventory location key
    """
    logger.info(f"Creating goods receipt for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        payload = {
            "Date": date,
            "Supplier": supplier_key,
            "Lines": [
                {"InventoryItem": l.get("inventory_item_key", ""), "Qty": float(l.get("qty", 0))}
                for l in lines
            ],
        }
        if reference:
            payload["Reference"] = reference
        if description:
            payload["Description"] = description
        if purchase_order_key:
            payload["PurchaseOrder"] = purchase_order_key
        if inventory_location_key:
            payload["InventoryLocation"] = inventory_location_key
        
        result = await client.create_goods_receipt(payload)
        return {"success": result.success, "key": result.key, "message": result.message, "entry_type": "goods_receipt"}
    except (CompanyNotFoundError, ManagerIOError) as e:
        return {"success": False, "key": None, "message": str(e), "entry_type": "goods_receipt"}


@tool
async def create_inventory_write_off(
    company_id: str,
    user_id: str,
    date: str,
    lines: List[Dict[str, Any]],
    reference: Optional[str] = None,
    description: Optional[str] = None,
    inventory_location_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an inventory write-off in Manager.io.
    
    Records inventory that is damaged, lost, expired, or otherwise removed from stock.
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        date: Write-off date in YYYY-MM-DD format
        lines: List of line items, each with: inventory_item_key, qty
        reference: Optional reference number
        description: Optional description/reason for write-off
        inventory_location_key: Optional inventory location key
    """
    logger.info(f"Creating inventory write-off for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        payload = {
            "Date": date,
            "Lines": [
                {"InventoryItem": l.get("inventory_item_key", ""), "Qty": float(l.get("qty", 0))}
                for l in lines
            ],
        }
        if reference:
            payload["Reference"] = reference
        if description:
            payload["Description"] = description
        if inventory_location_key:
            payload["InventoryLocation"] = inventory_location_key
        
        result = await client.create_inventory_write_off(payload)
        return {"success": result.success, "key": result.key, "message": result.message, "entry_type": "inventory_write_off"}
    except (CompanyNotFoundError, ManagerIOError) as e:
        return {"success": False, "key": None, "message": str(e), "entry_type": "inventory_write_off"}


@tool
async def create_inventory_transfer(
    company_id: str,
    user_id: str,
    date: str,
    from_location_key: str,
    to_location_key: str,
    lines: List[Dict[str, Any]],
    reference: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an inventory transfer in Manager.io.
    
    Moves inventory between locations (warehouses, stores, etc.).
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        date: Transfer date in YYYY-MM-DD format
        from_location_key: Source inventory location key
        to_location_key: Destination inventory location key
        lines: List of line items, each with: inventory_item_key, qty
        reference: Optional reference number
        description: Optional description
    """
    logger.info(f"Creating inventory transfer for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        payload = {
            "Date": date,
            "FromLocation": from_location_key,
            "ToLocation": to_location_key,
            "Lines": [
                {"InventoryItem": l.get("inventory_item_key", ""), "Qty": float(l.get("qty", 0))}
                for l in lines
            ],
        }
        if reference:
            payload["Reference"] = reference
        if description:
            payload["Description"] = description
        
        result = await client.create_inventory_transfer(payload)
        return {"success": result.success, "key": result.key, "message": result.message, "entry_type": "inventory_transfer"}
    except (CompanyNotFoundError, ManagerIOError) as e:
        return {"success": False, "key": None, "message": str(e), "entry_type": "inventory_transfer"}


# =============================================================================
# Investment Tools
# =============================================================================


@tool
async def get_investments(company_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetch investments from Manager.io.
    
    Returns list of investment holdings (stocks, bonds, mutual funds, etc.).
    """
    logger.info(f"Fetching investments for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        investments = await client.get_investments()
        return [
            {
                "key": inv.get("Key", inv.get("key", "")),
                "code": inv.get("Code", inv.get("code", "")),
                "name": inv.get("Name", inv.get("name", "")),
                "qty": float(inv.get("Qty", inv.get("qty", 0)) or 0),
                "market_value": float(inv.get("MarketValue", inv.get("market_value", 0)) or 0),
            }
            for inv in investments
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching investments: {e}")
        raise


@tool
async def get_investment_transactions(company_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch investment transactions from Manager.io.
    
    Returns buy/sell/dividend transactions for investments.
    """
    logger.info(f"Fetching investment transactions for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        response = await client.get_investment_transactions(skip=0, take=limit)
        return [
            {
                "key": item.get("Key", item.get("key", "")),
                "date": item.get("Date", item.get("date", "")),
                "investment": item.get("Investment", item.get("investment", "")),
                "description": item.get("Description", item.get("description", "")),
                "qty": float(item.get("Qty", item.get("qty", 0)) or 0),
                "debit": float(item.get("Debit", item.get("debit", 0)) or 0),
                "credit": float(item.get("Credit", item.get("credit", 0)) or 0),
            }
            for item in response.items
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching investment transactions: {e}")
        raise


@tool
async def get_investment_market_prices(company_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetch investment market prices from Manager.io.
    
    Returns current market price records for investments.
    """
    logger.info(f"Fetching investment market prices for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        prices = await client.get_investment_market_prices()
        return [
            {
                "key": p.get("Key", p.get("key", "")),
                "date": p.get("Date", p.get("date", "")),
                "investment": p.get("Investment", p.get("investment", "")),
            }
            for p in prices
        ]
    except (CompanyNotFoundError, ManagerIOError) as e:
        logger.error(f"Error fetching investment market prices: {e}")
        raise


@tool
async def create_investment(
    company_id: str,
    user_id: str,
    name: str,
    code: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an investment in Manager.io.
    
    Creates a new investment holding (stock, bond, mutual fund, etc.).
    
    Args:
        company_id: The company configuration ID
        user_id: The user ID for access control
        name: Investment name (e.g., "Apple Inc.", "US Treasury Bond")
        code: Optional investment code/ticker symbol
    """
    logger.info(f"Creating investment for company {company_id}")
    try:
        context = get_tool_context()
        client = await context.get_manager_io_client(company_id, user_id)
        
        payload = {"Name": name}
        if code:
            payload["Code"] = code
        
        result = await client.create_investment(payload)
        return {"success": result.success, "key": result.key, "message": result.message, "entry_type": "investment"}
    except (CompanyNotFoundError, ManagerIOError) as e:
        return {"success": False, "key": None, "message": str(e), "entry_type": "investment"}


# =============================================================================
# Tool Registry
# =============================================================================


# List of all data fetching tools for easy registration with LangChain agent
DATA_FETCHING_TOOLS = [
    get_chart_of_accounts,
    get_suppliers,
    get_customers,
    get_recent_transactions,
    get_account_balances,
    get_bank_accounts,
    get_employees,
    get_credit_notes,
    get_debit_notes,
    get_inventory_items,
    get_inventory_kits,
    get_sales_invoices,
    get_purchase_invoices,
    get_sales_orders,
    get_purchase_orders,
    get_goods_receipts,
    get_delivery_notes,
    get_tax_codes,
    get_fixed_assets,
    get_projects,
    get_investments,
    get_investment_transactions,
    get_investment_market_prices,
]


# List of all document processing tools
DOCUMENT_PROCESSING_TOOLS = [
    extract_document_data,
    categorize_expense,
    identify_supplier,
]


# List of all submission tools
SUBMISSION_TOOLS = [
    create_expense_claim,
    create_purchase_invoice,
    create_sales_invoice,
    create_payment,
    create_receipt,
    create_journal_entry,
    create_transfer,
    create_credit_note,
    create_debit_note,
    create_goods_receipt,
    create_inventory_write_off,
    create_inventory_transfer,
    create_investment,
    amend_entry,
    delete_entry,
    handle_forex,
]


# List of all report tools
REPORT_TOOLS = [
    get_balance_sheet,
    get_profit_and_loss,
    get_trial_balance,
    get_aged_receivables,
    get_aged_payables,
]


def get_data_fetching_tools() -> List:
    """Get all data fetching tools for agent registration."""
    return DATA_FETCHING_TOOLS.copy()


def get_document_processing_tools() -> List:
    """Get all document processing tools for agent registration."""
    return DOCUMENT_PROCESSING_TOOLS.copy()


def get_submission_tools() -> List:
    """Get all submission tools for agent registration."""
    return SUBMISSION_TOOLS.copy()


def get_report_tools() -> List:
    """Get all report tools for agent registration."""
    return REPORT_TOOLS.copy()


def get_all_tools() -> List:
    """Get all agent tools for registration."""
    return (
        DATA_FETCHING_TOOLS.copy() +
        DOCUMENT_PROCESSING_TOOLS.copy() +
        SUBMISSION_TOOLS.copy() +
        REPORT_TOOLS.copy()
    )
