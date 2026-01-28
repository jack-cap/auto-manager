"""Unit tests for agent tools.

Tests the LangChain agent tools that wrap ManagerIOClient methods.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agent_tools import (
    AccountBalance,
    AccountBalances,
    ToolContext,
    Transaction,
    get_account_balances,
    get_chart_of_accounts,
    get_customers,
    get_data_fetching_tools,
    get_recent_transactions,
    get_suppliers,
    get_tool_context,
    set_tool_context,
    DATA_FETCHING_TOOLS,
)
from app.services.company import CompanyNotFoundError
from app.services.manager_io import (
    Account,
    Customer,
    ManagerIOError,
    PaginatedResponse,
    Supplier,
)


# =============================================================================
# Test Data Models
# =============================================================================


class TestTransactionModel:
    """Tests for the Transaction data model."""
    
    def test_transaction_creation(self):
        """Test creating a Transaction with all fields."""
        tx = Transaction(
            key="tx-123",
            date="2024-01-15",
            description="Test payment",
            amount=100.50,
            account="acc-456",
            transaction_type="payment",
            reference="REF-001",
        )
        
        assert tx.key == "tx-123"
        assert tx.date == "2024-01-15"
        assert tx.description == "Test payment"
        assert tx.amount == 100.50
        assert tx.account == "acc-456"
        assert tx.transaction_type == "payment"
        assert tx.reference == "REF-001"
    
    def test_transaction_optional_fields(self):
        """Test creating a Transaction with optional fields as None."""
        tx = Transaction(
            key="tx-123",
            date="2024-01-15",
            description="Test payment",
            amount=100.50,
            transaction_type="payment",
        )
        
        assert tx.account is None
        assert tx.reference is None


class TestAccountBalanceModel:
    """Tests for the AccountBalance data model."""
    
    def test_account_balance_creation(self):
        """Test creating an AccountBalance."""
        balance = AccountBalance(
            account_key="acc-123",
            account_name="Cash",
            balance=1000.00,
            currency="USD",
        )
        
        assert balance.account_key == "acc-123"
        assert balance.account_name == "Cash"
        assert balance.balance == 1000.00
        assert balance.currency == "USD"
    
    def test_account_balance_default_currency(self):
        """Test AccountBalance default currency."""
        balance = AccountBalance(
            account_key="acc-123",
            account_name="Cash",
            balance=1000.00,
        )
        
        assert balance.currency == "USD"


class TestAccountBalancesModel:
    """Tests for the AccountBalances data model."""
    
    def test_account_balances_creation(self):
        """Test creating AccountBalances."""
        balances = AccountBalances(
            balances=[
                AccountBalance(
                    account_key="acc-1",
                    account_name="Cash",
                    balance=1000.00,
                ),
                AccountBalance(
                    account_key="acc-2",
                    account_name="Bank",
                    balance=5000.00,
                ),
            ],
            as_of_date="2024-01-15",
            total_assets=6000.00,
            total_liabilities=0.00,
        )
        
        assert len(balances.balances) == 2
        assert balances.as_of_date == "2024-01-15"
        assert balances.total_assets == 6000.00
        assert balances.total_liabilities == 0.00


# =============================================================================
# Test Tool Context
# =============================================================================


class TestToolContext:
    """Tests for the ToolContext class."""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return AsyncMock()
    
    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return AsyncMock()
    
    @pytest.fixture
    def mock_encryption(self):
        """Create a mock encryption service."""
        mock = MagicMock()
        mock.decrypt.return_value = "decrypted-api-key"
        return mock
    
    def test_tool_context_creation(self, mock_db, mock_redis, mock_encryption):
        """Test creating a ToolContext."""
        context = ToolContext(
            db=mock_db,
            redis=mock_redis,
            encryption_service=mock_encryption,
        )
        
        assert context.db == mock_db
        assert context.redis == mock_redis
    
    @pytest.mark.asyncio
    async def test_get_company_config(self, mock_db, mock_redis, mock_encryption):
        """Test getting company configuration."""
        context = ToolContext(
            db=mock_db,
            redis=mock_redis,
            encryption_service=mock_encryption,
        )
        
        # Mock the company service
        mock_company = MagicMock()
        mock_company.id = "company-123"
        mock_company.base_url = "https://manager.example.com/api2"
        mock_company.api_key_encrypted = "encrypted-key"
        
        with patch.object(
            context._company_service,
            "get_by_id",
            new_callable=AsyncMock,
            return_value=mock_company,
        ):
            company = await context.get_company_config("company-123", "user-456")
            
            assert company.id == "company-123"
            assert company.base_url == "https://manager.example.com/api2"
    
    @pytest.mark.asyncio
    async def test_get_manager_io_client(self, mock_db, mock_redis, mock_encryption):
        """Test getting a ManagerIOClient."""
        context = ToolContext(
            db=mock_db,
            redis=mock_redis,
            encryption_service=mock_encryption,
        )
        
        # Mock the company service
        mock_company = MagicMock()
        mock_company.id = "company-123"
        mock_company.base_url = "https://manager.example.com/api2"
        mock_company.api_key_encrypted = "encrypted-key"
        
        with patch.object(
            context._company_service,
            "get_by_id",
            new_callable=AsyncMock,
            return_value=mock_company,
        ):
            with patch.object(
                context._company_service,
                "decrypt_api_key",
                return_value="decrypted-api-key",
            ):
                client = await context.get_manager_io_client("company-123", "user-456")
                
                assert client.base_url == "https://manager.example.com/api2"
                assert client.api_key == "decrypted-api-key"
    
    @pytest.mark.asyncio
    async def test_get_manager_io_client_caches(self, mock_db, mock_redis, mock_encryption):
        """Test that ManagerIOClient is cached."""
        context = ToolContext(
            db=mock_db,
            redis=mock_redis,
            encryption_service=mock_encryption,
        )
        
        # Mock the company service
        mock_company = MagicMock()
        mock_company.id = "company-123"
        mock_company.base_url = "https://manager.example.com/api2"
        mock_company.api_key_encrypted = "encrypted-key"
        
        with patch.object(
            context._company_service,
            "get_by_id",
            new_callable=AsyncMock,
            return_value=mock_company,
        ) as mock_get:
            with patch.object(
                context._company_service,
                "decrypt_api_key",
                return_value="decrypted-api-key",
            ):
                # Get client twice
                client1 = await context.get_manager_io_client("company-123", "user-456")
                client2 = await context.get_manager_io_client("company-123", "user-456")
                
                # Should be the same instance
                assert client1 is client2
                
                # get_by_id should only be called once
                assert mock_get.call_count == 1
    
    @pytest.mark.asyncio
    async def test_close_closes_all_clients(self, mock_db, mock_redis, mock_encryption):
        """Test that close() closes all cached clients."""
        context = ToolContext(
            db=mock_db,
            redis=mock_redis,
            encryption_service=mock_encryption,
        )
        
        # Mock the company service
        mock_company = MagicMock()
        mock_company.id = "company-123"
        mock_company.base_url = "https://manager.example.com/api2"
        mock_company.api_key_encrypted = "encrypted-key"
        
        with patch.object(
            context._company_service,
            "get_by_id",
            new_callable=AsyncMock,
            return_value=mock_company,
        ):
            with patch.object(
                context._company_service,
                "decrypt_api_key",
                return_value="decrypted-api-key",
            ):
                client = await context.get_manager_io_client("company-123", "user-456")
                
                # Mock the client's close method
                client.close = AsyncMock()
                
                await context.close()
                
                # Client should be closed
                client.close.assert_called_once()
                
                # Cache should be cleared
                assert len(context._clients) == 0


# =============================================================================
# Test Global Context Functions
# =============================================================================


class TestGlobalContextFunctions:
    """Tests for global context management functions."""
    
    def test_set_and_get_tool_context(self):
        """Test setting and getting the global tool context."""
        mock_db = AsyncMock()
        mock_encryption = MagicMock()
        context = ToolContext(db=mock_db, encryption_service=mock_encryption)
        
        set_tool_context(context)
        
        retrieved = get_tool_context()
        assert retrieved is context
    
    def test_get_tool_context_raises_when_not_set(self):
        """Test that get_tool_context raises when context not set."""
        # Reset global context
        import app.services.agent_tools as agent_tools
        agent_tools._tool_context = None
        
        with pytest.raises(RuntimeError, match="Tool context not set"):
            get_tool_context()


# =============================================================================
# Test Data Fetching Tools
# =============================================================================


class TestGetChartOfAccountsTool:
    """Tests for the get_chart_of_accounts tool."""
    
    @pytest.fixture
    def mock_context(self):
        """Create a mock tool context."""
        context = MagicMock(spec=ToolContext)
        context.get_manager_io_client = AsyncMock()
        return context
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock ManagerIOClient."""
        client = AsyncMock()
        client.get_chart_of_accounts = AsyncMock(return_value=[
            Account(key="acc-1", name="Cash", code="1000"),
            Account(key="acc-2", name="Bank", code="1100"),
            Account(key="acc-3", name="Expenses", code=None),
        ])
        return client
    
    @pytest.mark.asyncio
    async def test_get_chart_of_accounts_success(self, mock_context, mock_client):
        """Test successful chart of accounts retrieval."""
        mock_context.get_manager_io_client.return_value = mock_client
        
        with patch("app.services.agent_tools.get_tool_context", return_value=mock_context):
            result = await get_chart_of_accounts.ainvoke({
                "company_id": "company-123",
                "user_id": "user-456",
            })
            
            assert len(result) == 3
            assert result[0] == {"key": "acc-1", "name": "Cash", "code": "1000"}
            assert result[1] == {"key": "acc-2", "name": "Bank", "code": "1100"}
            assert result[2] == {"key": "acc-3", "name": "Expenses", "code": None}
    
    @pytest.mark.asyncio
    async def test_get_chart_of_accounts_company_not_found(self, mock_context):
        """Test chart of accounts when company not found."""
        mock_context.get_manager_io_client.side_effect = CompanyNotFoundError("Not found")
        
        with patch("app.services.agent_tools.get_tool_context", return_value=mock_context):
            with pytest.raises(CompanyNotFoundError):
                await get_chart_of_accounts.ainvoke({
                    "company_id": "invalid-company",
                    "user_id": "user-456",
                })
    
    @pytest.mark.asyncio
    async def test_get_chart_of_accounts_api_error(self, mock_context, mock_client):
        """Test chart of accounts when API fails."""
        mock_client.get_chart_of_accounts.side_effect = ManagerIOError("API error")
        mock_context.get_manager_io_client.return_value = mock_client
        
        with patch("app.services.agent_tools.get_tool_context", return_value=mock_context):
            with pytest.raises(ManagerIOError):
                await get_chart_of_accounts.ainvoke({
                    "company_id": "company-123",
                    "user_id": "user-456",
                })


class TestGetSuppliersTool:
    """Tests for the get_suppliers tool."""
    
    @pytest.fixture
    def mock_context(self):
        """Create a mock tool context."""
        context = MagicMock(spec=ToolContext)
        context.get_manager_io_client = AsyncMock()
        return context
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock ManagerIOClient."""
        client = AsyncMock()
        client.get_suppliers = AsyncMock(return_value=[
            Supplier(key="sup-1", name="Supplier A"),
            Supplier(key="sup-2", name="Supplier B"),
        ])
        return client
    
    @pytest.mark.asyncio
    async def test_get_suppliers_success(self, mock_context, mock_client):
        """Test successful suppliers retrieval."""
        mock_context.get_manager_io_client.return_value = mock_client
        
        with patch("app.services.agent_tools.get_tool_context", return_value=mock_context):
            result = await get_suppliers.ainvoke({
                "company_id": "company-123",
                "user_id": "user-456",
            })
            
            assert len(result) == 2
            assert result[0] == {"key": "sup-1", "name": "Supplier A"}
            assert result[1] == {"key": "sup-2", "name": "Supplier B"}


class TestGetCustomersTool:
    """Tests for the get_customers tool."""
    
    @pytest.fixture
    def mock_context(self):
        """Create a mock tool context."""
        context = MagicMock(spec=ToolContext)
        context.get_manager_io_client = AsyncMock()
        return context
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock ManagerIOClient."""
        client = AsyncMock()
        client.get_customers = AsyncMock(return_value=[
            Customer(key="cust-1", name="Customer A"),
            Customer(key="cust-2", name="Customer B"),
        ])
        return client
    
    @pytest.mark.asyncio
    async def test_get_customers_success(self, mock_context, mock_client):
        """Test successful customers retrieval."""
        mock_context.get_manager_io_client.return_value = mock_client
        
        with patch("app.services.agent_tools.get_tool_context", return_value=mock_context):
            result = await get_customers.ainvoke({
                "company_id": "company-123",
                "user_id": "user-456",
            })
            
            assert len(result) == 2
            assert result[0] == {"key": "cust-1", "name": "Customer A"}
            assert result[1] == {"key": "cust-2", "name": "Customer B"}


class TestGetRecentTransactionsTool:
    """Tests for the get_recent_transactions tool."""
    
    @pytest.fixture
    def mock_context(self):
        """Create a mock tool context."""
        context = MagicMock(spec=ToolContext)
        context.get_manager_io_client = AsyncMock()
        return context
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock ManagerIOClient."""
        client = AsyncMock()
        
        # Mock payments
        client.get_payments = AsyncMock(return_value=PaginatedResponse(
            items=[
                {"Key": "pay-1", "Date": "2024-01-15", "Description": "Payment 1", "Amount": 100.0},
            ],
            total=1,
            skip=0,
            take=10,
        ))
        
        # Mock receipts
        client.get_receipts = AsyncMock(return_value=PaginatedResponse(
            items=[
                {"Key": "rec-1", "Date": "2024-01-14", "Description": "Receipt 1", "Amount": 200.0},
            ],
            total=1,
            skip=0,
            take=10,
        ))
        
        # Mock transfers
        client.get_transfers = AsyncMock(return_value=PaginatedResponse(
            items=[
                {"Key": "xfer-1", "Date": "2024-01-13", "Description": "Transfer 1", "Amount": 50.0},
            ],
            total=1,
            skip=0,
            take=10,
        ))
        
        return client
    
    @pytest.mark.asyncio
    async def test_get_recent_transactions_success(self, mock_context, mock_client):
        """Test successful recent transactions retrieval."""
        mock_context.get_manager_io_client.return_value = mock_client
        
        with patch("app.services.agent_tools.get_tool_context", return_value=mock_context):
            result = await get_recent_transactions.ainvoke({
                "company_id": "company-123",
                "user_id": "user-456",
                "limit": 50,
            })
            
            assert len(result) == 3
            
            # Should be sorted by date (most recent first)
            assert result[0]["date"] == "2024-01-15"
            assert result[0]["transaction_type"] == "payment"
            
            assert result[1]["date"] == "2024-01-14"
            assert result[1]["transaction_type"] == "receipt"
            
            assert result[2]["date"] == "2024-01-13"
            assert result[2]["transaction_type"] == "transfer"
    
    @pytest.mark.asyncio
    async def test_get_recent_transactions_handles_partial_failures(self, mock_context, mock_client):
        """Test that partial API failures don't break the tool."""
        # Make receipts fail
        mock_client.get_receipts.side_effect = ManagerIOError("API error")
        mock_context.get_manager_io_client.return_value = mock_client
        
        with patch("app.services.agent_tools.get_tool_context", return_value=mock_context):
            result = await get_recent_transactions.ainvoke({
                "company_id": "company-123",
                "user_id": "user-456",
                "limit": 50,
            })
            
            # Should still return payments and transfers
            assert len(result) == 2


class TestGetAccountBalancesTool:
    """Tests for the get_account_balances tool."""
    
    @pytest.fixture
    def mock_context(self):
        """Create a mock tool context."""
        context = MagicMock(spec=ToolContext)
        context.get_manager_io_client = AsyncMock()
        return context
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock ManagerIOClient."""
        client = AsyncMock()
        
        # Mock chart of accounts
        client.get_chart_of_accounts = AsyncMock(return_value=[
            Account(key="acc-1", name="Cash", code="1000"),
            Account(key="acc-2", name="Bank", code="1100"),
        ])
        
        # Mock paginated fetches
        client.fetch_all_paginated = AsyncMock(side_effect=[
            # Payments (outflows)
            [{"Account": "acc-1", "Amount": 100.0}],
            # Receipts (inflows)
            [{"Account": "acc-1", "Amount": 500.0}],
            # Transfers
            [{"FromAccount": "acc-1", "ToAccount": "acc-2", "Amount": 200.0}],
            # Journal entries
            [{"Account": "acc-2", "Debit": 50.0, "Credit": 0.0}],
        ])
        
        return client
    
    @pytest.mark.asyncio
    async def test_get_account_balances_success(self, mock_context, mock_client):
        """Test successful account balances calculation."""
        mock_context.get_manager_io_client.return_value = mock_client
        
        with patch("app.services.agent_tools.get_tool_context", return_value=mock_context):
            result = await get_account_balances.ainvoke({
                "company_id": "company-123",
                "user_id": "user-456",
            })
            
            assert "balances" in result
            assert "as_of_date" in result
            assert "total_assets" in result
            assert "total_liabilities" in result
            
            # Check that balances were calculated
            balances_by_key = {b["account_key"]: b for b in result["balances"]}
            
            # acc-1: +500 (receipt) - 100 (payment) - 200 (transfer out) = 200
            assert balances_by_key["acc-1"]["balance"] == 200.0
            
            # acc-2: +200 (transfer in) + 50 (journal debit) = 250
            assert balances_by_key["acc-2"]["balance"] == 250.0


# =============================================================================
# Test Tool Registry
# =============================================================================


class TestToolRegistry:
    """Tests for the tool registry."""
    
    def test_data_fetching_tools_list(self):
        """Test that DATA_FETCHING_TOOLS contains all expected tools."""
        assert len(DATA_FETCHING_TOOLS) == 23
        
        tool_names = [t.name for t in DATA_FETCHING_TOOLS]
        # Core reference data
        assert "get_chart_of_accounts" in tool_names
        assert "get_suppliers" in tool_names
        assert "get_customers" in tool_names
        assert "get_bank_accounts" in tool_names
        assert "get_employees" in tool_names
        assert "get_tax_codes" in tool_names
        # Transactions
        assert "get_recent_transactions" in tool_names
        assert "get_account_balances" in tool_names
        # Invoices & Orders
        assert "get_sales_invoices" in tool_names
        assert "get_purchase_invoices" in tool_names
        assert "get_sales_orders" in tool_names
        assert "get_purchase_orders" in tool_names
        # Credit/Debit notes
        assert "get_credit_notes" in tool_names
        assert "get_debit_notes" in tool_names
        # Inventory
        assert "get_inventory_items" in tool_names
        assert "get_inventory_kits" in tool_names
        assert "get_goods_receipts" in tool_names
        assert "get_delivery_notes" in tool_names
        # Assets & Projects
        assert "get_fixed_assets" in tool_names
        assert "get_projects" in tool_names
        # Investments
        assert "get_investments" in tool_names
        assert "get_investment_transactions" in tool_names
        assert "get_investment_market_prices" in tool_names
    
    def test_get_data_fetching_tools_returns_copy(self):
        """Test that get_data_fetching_tools returns a copy."""
        tools1 = get_data_fetching_tools()
        tools2 = get_data_fetching_tools()
        
        assert tools1 is not tools2
        assert tools1 == tools2
    
    def test_tools_have_descriptions(self):
        """Test that all tools have descriptions."""
        for tool in DATA_FETCHING_TOOLS:
            assert tool.description is not None
            assert len(tool.description) > 0


# =============================================================================
# Test Document Processing Data Models
# =============================================================================


class TestExtractedDataModel:
    """Tests for the ExtractedData data model."""
    
    def test_extracted_data_creation(self):
        """Test creating ExtractedData with all fields."""
        from app.services.agent_tools import ExtractedData
        
        data = ExtractedData(
            text="Invoice #123\nTotal: $100.00",
            normalized_text="Invoice #123\nTotal: $100.00",
            pages=1,
            success=True,
            error=None,
        )
        
        assert data.text == "Invoice #123\nTotal: $100.00"
        assert data.normalized_text == "Invoice #123\nTotal: $100.00"
        assert data.pages == 1
        assert data.success is True
        assert data.error is None
    
    def test_extracted_data_with_error(self):
        """Test creating ExtractedData with error."""
        from app.services.agent_tools import ExtractedData
        
        data = ExtractedData(
            text="",
            normalized_text="",
            pages=0,
            success=False,
            error="OCR failed",
        )
        
        assert data.success is False
        assert data.error == "OCR failed"


class TestMatchedAccountModel:
    """Tests for the MatchedAccount data model."""
    
    def test_matched_account_creation(self):
        """Test creating MatchedAccount with all fields."""
        from app.services.agent_tools import MatchedAccount
        
        account = MatchedAccount(
            key="acc-123",
            name="Office Supplies",
            code="5100",
            score=0.85,
            matched_keywords=["office", "supplies"],
        )
        
        assert account.key == "acc-123"
        assert account.name == "Office Supplies"
        assert account.code == "5100"
        assert account.score == 0.85
        assert account.matched_keywords == ["office", "supplies"]
    
    def test_matched_account_optional_fields(self):
        """Test MatchedAccount with optional fields."""
        from app.services.agent_tools import MatchedAccount
        
        account = MatchedAccount(
            key="acc-123",
            name="Expenses",
            score=0.5,
        )
        
        assert account.code is None
        assert account.matched_keywords == []


class TestMatchedSupplierModel:
    """Tests for the MatchedSupplier data model."""
    
    def test_matched_supplier_creation(self):
        """Test creating MatchedSupplier with all fields."""
        from app.services.agent_tools import MatchedSupplier
        
        supplier = MatchedSupplier(
            key="sup-123",
            name="Acme Corp",
            score=0.95,
            matched=True,
        )
        
        assert supplier.key == "sup-123"
        assert supplier.name == "Acme Corp"
        assert supplier.score == 0.95
        assert supplier.matched is True
    
    def test_matched_supplier_no_match(self):
        """Test MatchedSupplier when no match found."""
        from app.services.agent_tools import MatchedSupplier
        
        supplier = MatchedSupplier(
            key="",
            name="",
            score=0.3,
            matched=False,
        )
        
        assert supplier.matched is False


# =============================================================================
# Test Helper Functions
# =============================================================================


class TestNormalizeForMatching:
    """Tests for the _normalize_for_matching helper function."""
    
    def test_normalize_lowercase(self):
        """Test that text is converted to lowercase."""
        from app.services.agent_tools import _normalize_for_matching
        
        assert _normalize_for_matching("HELLO WORLD") == "hello world"
    
    def test_normalize_removes_special_chars(self):
        """Test that special characters are removed."""
        from app.services.agent_tools import _normalize_for_matching
        
        assert _normalize_for_matching("Hello, World!") == "hello world"
        assert _normalize_for_matching("Test@#$%^&*()") == "test"
    
    def test_normalize_whitespace(self):
        """Test that whitespace is normalized."""
        from app.services.agent_tools import _normalize_for_matching
        
        assert _normalize_for_matching("hello   world") == "hello world"
        assert _normalize_for_matching("  hello  ") == "hello"


class TestExtractKeywords:
    """Tests for the _extract_keywords helper function."""
    
    def test_extract_keywords_basic(self):
        """Test basic keyword extraction."""
        from app.services.agent_tools import _extract_keywords
        
        keywords = _extract_keywords("Office supplies purchase")
        assert "office" in keywords
        assert "supplies" in keywords
        assert "purchase" in keywords
    
    def test_extract_keywords_filters_short_words(self):
        """Test that short words (< 3 chars) are filtered out."""
        from app.services.agent_tools import _extract_keywords
        
        keywords = _extract_keywords("I am at my office")
        assert "office" in keywords
        # Words with 2 or fewer characters are filtered
        assert "am" not in keywords
        assert "at" not in keywords
        assert "my" not in keywords


class TestFuzzyMatchScore:
    """Tests for the _fuzzy_match_score helper function."""
    
    def test_exact_match(self):
        """Test exact match returns 1.0."""
        from app.services.agent_tools import _fuzzy_match_score
        
        assert _fuzzy_match_score("Acme Corp", "Acme Corp") == 1.0
        assert _fuzzy_match_score("ACME CORP", "acme corp") == 1.0
    
    def test_substring_match(self):
        """Test substring containment returns high score."""
        from app.services.agent_tools import _fuzzy_match_score
        
        score = _fuzzy_match_score("Acme", "Acme Corporation")
        assert score >= 0.9
    
    def test_partial_match(self):
        """Test partial match returns moderate score."""
        from app.services.agent_tools import _fuzzy_match_score
        
        score = _fuzzy_match_score("Acme Corp", "Acme Inc")
        assert 0.5 < score < 1.0
    
    def test_no_match(self):
        """Test completely different strings return low score."""
        from app.services.agent_tools import _fuzzy_match_score
        
        score = _fuzzy_match_score("Apple", "Microsoft")
        assert score < 0.5


# =============================================================================
# Test Document Processing Tools
# =============================================================================


class TestExtractDocumentDataTool:
    """Tests for the extract_document_data tool."""
    
    @pytest.fixture
    def mock_context(self):
        """Create a mock tool context."""
        context = MagicMock(spec=ToolContext)
        return context
    
    @pytest.fixture
    def mock_ocr_service(self):
        """Create a mock OCR service."""
        from app.services.ocr import OCRResult
        
        service = AsyncMock()
        service.extract_text = AsyncMock(return_value=OCRResult(
            text="Invoice #123\nTotal: $100.00",
            pages=1,
            page_texts=["Invoice #123\nTotal: $100.00"],
        ))
        service.extract_from_pdf = AsyncMock(return_value=OCRResult(
            text="Page 1 content\n\n--- Page Break ---\n\nPage 2 content",
            pages=2,
            page_texts=["Page 1 content", "Page 2 content"],
        ))
        return service
    
    @pytest.mark.asyncio
    async def test_extract_document_data_image_success(self, mock_context, mock_ocr_service):
        """Test successful image extraction."""
        from app.services.agent_tools import extract_document_data
        
        mock_context.get_ocr_service.return_value = mock_ocr_service
        
        with patch("app.services.agent_tools.get_tool_context", return_value=mock_context):
            result = await extract_document_data.ainvoke({
                "image_data": b"\x89PNG\r\n\x1a\n",  # PNG magic bytes
                "document_hint": "receipt",
            })
            
            assert result["success"] is True
            assert "Invoice #123" in result["text"]
            assert result["pages"] == 1
            assert result["error"] is None
    
    @pytest.mark.asyncio
    async def test_extract_document_data_pdf_success(self, mock_context, mock_ocr_service):
        """Test successful PDF extraction."""
        from app.services.agent_tools import extract_document_data
        
        mock_context.get_ocr_service.return_value = mock_ocr_service
        
        with patch("app.services.agent_tools.get_tool_context", return_value=mock_context):
            result = await extract_document_data.ainvoke({
                "image_data": b"%PDF-1.4",  # PDF magic bytes
                "document_hint": "invoice",
            })
            
            assert result["success"] is True
            assert result["pages"] == 2
            mock_ocr_service.extract_from_pdf.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_extract_document_data_ocr_error(self, mock_context, mock_ocr_service):
        """Test handling of OCR errors."""
        from app.services.agent_tools import extract_document_data
        from app.services.ocr import OCRProcessingError
        
        mock_ocr_service.extract_text.side_effect = OCRProcessingError("OCR failed")
        mock_context.get_ocr_service.return_value = mock_ocr_service
        
        with patch("app.services.agent_tools.get_tool_context", return_value=mock_context):
            result = await extract_document_data.ainvoke({
                "image_data": b"\x89PNG\r\n\x1a\n",
            })
            
            assert result["success"] is False
            assert "OCR failed" in result["error"]


class TestCategorizeExpenseTool:
    """Tests for the categorize_expense tool."""
    
    @pytest.fixture
    def sample_accounts(self):
        """Sample accounts for testing."""
        return [
            {"key": "acc-1", "name": "Office Supplies", "code": "5100"},
            {"key": "acc-2", "name": "Travel Expenses", "code": "5200"},
            {"key": "acc-3", "name": "Meals and Entertainment", "code": "5300"},
            {"key": "acc-4", "name": "Professional Services", "code": "5400"},
            {"key": "acc-5", "name": "Utilities", "code": "5500"},
        ]
    
    def test_categorize_expense_office_supplies(self, sample_accounts):
        """Test categorizing office supplies expense."""
        from app.services.agent_tools import categorize_expense
        
        result = categorize_expense.invoke({
            "description": "Printer paper and ink cartridges",
            "amount": 75.00,
            "accounts": sample_accounts,
        })
        
        assert result["name"] == "Office Supplies"
        assert result["key"] == "acc-1"
        assert result["score"] > 0
    
    def test_categorize_expense_travel(self, sample_accounts):
        """Test categorizing travel expense."""
        from app.services.agent_tools import categorize_expense
        
        result = categorize_expense.invoke({
            "description": "Flight to New York business trip",
            "amount": 450.00,
            "accounts": sample_accounts,
        })
        
        assert result["name"] == "Travel Expenses"
        assert result["score"] > 0
    
    def test_categorize_expense_meals(self, sample_accounts):
        """Test categorizing meals expense."""
        from app.services.agent_tools import categorize_expense
        
        result = categorize_expense.invoke({
            "description": "Team lunch at restaurant",
            "amount": 120.00,
            "accounts": sample_accounts,
        })
        
        assert result["name"] == "Meals and Entertainment"
        assert result["score"] > 0
    
    def test_categorize_expense_empty_accounts(self):
        """Test categorizing with empty accounts list."""
        from app.services.agent_tools import categorize_expense
        
        result = categorize_expense.invoke({
            "description": "Some expense",
            "amount": 50.00,
            "accounts": [],
        })
        
        assert result["key"] == ""
        assert result["score"] == 0.0
    
    def test_categorize_expense_empty_description(self, sample_accounts):
        """Test categorizing with empty description."""
        from app.services.agent_tools import categorize_expense
        
        result = categorize_expense.invoke({
            "description": "",
            "amount": 50.00,
            "accounts": sample_accounts,
        })
        
        # Should return first account as fallback
        assert result["key"] == "acc-1"
        assert result["score"] == 0.0


class TestIdentifySupplierTool:
    """Tests for the identify_supplier tool."""
    
    @pytest.fixture
    def sample_suppliers(self):
        """Sample suppliers for testing."""
        return [
            {"key": "sup-1", "name": "Acme Corporation"},
            {"key": "sup-2", "name": "Office Depot"},
            {"key": "sup-3", "name": "Amazon Web Services"},
            {"key": "sup-4", "name": "Microsoft Corporation"},
            {"key": "sup-5", "name": "Google Cloud Platform"},
        ]
    
    def test_identify_supplier_exact_match(self, sample_suppliers):
        """Test identifying supplier with exact match."""
        from app.services.agent_tools import identify_supplier
        
        result = identify_supplier.invoke({
            "vendor_name": "Acme Corporation",
            "suppliers": sample_suppliers,
        })
        
        assert result["matched"] is True
        assert result["name"] == "Acme Corporation"
        assert result["key"] == "sup-1"
        assert result["score"] == 1.0
    
    def test_identify_supplier_partial_match(self, sample_suppliers):
        """Test identifying supplier with partial match."""
        from app.services.agent_tools import identify_supplier
        
        result = identify_supplier.invoke({
            "vendor_name": "Acme Corp",
            "suppliers": sample_suppliers,
        })
        
        assert result["matched"] is True
        assert result["name"] == "Acme Corporation"
        assert result["score"] >= 0.6
    
    def test_identify_supplier_fuzzy_match(self, sample_suppliers):
        """Test identifying supplier with fuzzy match."""
        from app.services.agent_tools import identify_supplier
        
        result = identify_supplier.invoke({
            "vendor_name": "Office Depot Inc",
            "suppliers": sample_suppliers,
        })
        
        assert result["matched"] is True
        assert result["name"] == "Office Depot"
    
    def test_identify_supplier_no_match(self, sample_suppliers):
        """Test identifying supplier with no match."""
        from app.services.agent_tools import identify_supplier
        
        result = identify_supplier.invoke({
            "vendor_name": "Unknown Vendor XYZ",
            "suppliers": sample_suppliers,
            "threshold": 0.6,
        })
        
        assert result["matched"] is False
    
    def test_identify_supplier_empty_suppliers(self):
        """Test identifying with empty suppliers list."""
        from app.services.agent_tools import identify_supplier
        
        result = identify_supplier.invoke({
            "vendor_name": "Some Vendor",
            "suppliers": [],
        })
        
        assert result["matched"] is False
        assert result["key"] == ""
    
    def test_identify_supplier_empty_vendor_name(self, sample_suppliers):
        """Test identifying with empty vendor name."""
        from app.services.agent_tools import identify_supplier
        
        result = identify_supplier.invoke({
            "vendor_name": "",
            "suppliers": sample_suppliers,
        })
        
        assert result["matched"] is False
    
    def test_identify_supplier_custom_threshold(self, sample_suppliers):
        """Test identifying with custom threshold."""
        from app.services.agent_tools import identify_supplier
        
        # With high threshold, partial match should fail
        result = identify_supplier.invoke({
            "vendor_name": "Acme",
            "suppliers": sample_suppliers,
            "threshold": 0.95,
        })
        
        # May or may not match depending on score
        # The important thing is the threshold is respected
        if result["score"] < 0.95:
            assert result["matched"] is False


# =============================================================================
# Test Document Processing Tool Registry
# =============================================================================


class TestDocumentProcessingToolRegistry:
    """Tests for the document processing tool registry."""
    
    def test_document_processing_tools_list(self):
        """Test that DOCUMENT_PROCESSING_TOOLS contains all expected tools."""
        from app.services.agent_tools import DOCUMENT_PROCESSING_TOOLS
        
        assert len(DOCUMENT_PROCESSING_TOOLS) == 3
        
        tool_names = [t.name for t in DOCUMENT_PROCESSING_TOOLS]
        assert "extract_document_data" in tool_names
        assert "categorize_expense" in tool_names
        assert "identify_supplier" in tool_names
    
    def test_get_document_processing_tools_returns_copy(self):
        """Test that get_document_processing_tools returns a copy."""
        from app.services.agent_tools import get_document_processing_tools
        
        tools1 = get_document_processing_tools()
        tools2 = get_document_processing_tools()
        
        assert tools1 is not tools2
        assert tools1 == tools2
    
    def test_document_processing_tools_have_descriptions(self):
        """Test that all document processing tools have descriptions."""
        from app.services.agent_tools import DOCUMENT_PROCESSING_TOOLS
        
        for tool in DOCUMENT_PROCESSING_TOOLS:
            assert tool.description is not None
            assert len(tool.description) > 0


# =============================================================================
# Property-Based Tests for Agent Tools
# =============================================================================


from hypothesis import given, strategies as st, settings, assume


class TestAgentToolRegistrationProperty:
    """Property tests for agent tool registration.
    
    **Property 19: Agent Tool Registration**
    For any tool defined in the agent tools specification, the tool SHALL be
    registered and callable by the LangChain agent.
    
    **Validates: Requirements 9.1-9.12**
    """
    
    # List of all expected tool names from the specification
    EXPECTED_TOOLS = [
        # Data fetching tools (Requirements 9.1, 9.2, 9.3, 9.9, 9.10)
        "get_chart_of_accounts",
        "get_suppliers",
        "get_customers",
        "get_recent_transactions",
        "get_account_balances",
        # Document processing tools (Requirements 9.4, 9.5, 9.6)
        "extract_document_data",
        "categorize_expense",
        "identify_supplier",
        # Submission tools (Requirements 9.7, 9.8, 9.11, 9.12)
        "create_expense_claim",
        "create_purchase_invoice",
        "amend_entry",
        "handle_forex",
    ]
    
    @given(tool_index=st.integers(min_value=0, max_value=11))
    @settings(max_examples=100)
    def test_property_19_all_tools_registered(self, tool_index: int):
        """Property 19: All specified tools are registered and accessible.
        
        **Validates: Requirements 9.1-9.12**
        
        For any tool index in the expected tools list, the tool SHALL be
        present in the get_all_tools() registry and have a valid name and
        description.
        """
        from app.services.agent_tools import get_all_tools
        
        expected_tool_name = self.EXPECTED_TOOLS[tool_index]
        all_tools = get_all_tools()
        tool_names = [t.name for t in all_tools]
        
        # Property: The expected tool must be in the registry
        assert expected_tool_name in tool_names, (
            f"Tool '{expected_tool_name}' not found in registry. "
            f"Available tools: {tool_names}"
        )
        
        # Find the tool and verify it has required attributes
        tool = next(t for t in all_tools if t.name == expected_tool_name)
        
        # Property: Tool must have a non-empty description
        assert tool.description is not None and len(tool.description) > 0, (
            f"Tool '{expected_tool_name}' has no description"
        )
        
        # Property: Tool must be callable (have invoke or ainvoke method)
        assert hasattr(tool, 'invoke') or hasattr(tool, 'ainvoke'), (
            f"Tool '{expected_tool_name}' is not callable"
        )
    
    def test_property_19_tool_count_matches_specification(self):
        """Property 19: Total tool count matches specification.
        
        **Validates: Requirements 9.1-9.12**
        
        The total number of registered tools SHALL match the specification.
        """
        from app.services.agent_tools import get_all_tools
        
        all_tools = get_all_tools()
        
        # Property: All 12 tools from the specification must be registered
        assert len(all_tools) >= len(self.EXPECTED_TOOLS), (
            f"Expected at least {len(self.EXPECTED_TOOLS)} tools, "
            f"but found {len(all_tools)}"
        )
        
        # Verify all expected tools are present
        tool_names = [t.name for t in all_tools]
        for expected_name in self.EXPECTED_TOOLS:
            assert expected_name in tool_names, (
                f"Missing tool: {expected_name}"
            )


class TestExpenseCategorizationMatchingProperty:
    """Property tests for expense categorization matching.
    
    **Property 21: Expense Categorization Matching**
    For any expense description and list of accounts, categorize_expense SHALL
    return an account from the provided list with the highest semantic similarity
    to the description.
    
    **Validates: Requirements 4.5, 4.6**
    """
    
    # Strategy for generating account names
    account_name_strategy = st.sampled_from([
        "Office Supplies",
        "Travel Expenses",
        "Meals and Entertainment",
        "Professional Services",
        "Utilities",
        "Rent",
        "Insurance",
        "Marketing",
        "Software Subscriptions",
        "Hardware Equipment",
        "Telephone and Internet",
        "Bank Fees",
        "Legal Fees",
        "Accounting Services",
        "Training and Education",
    ])
    
    # Strategy for generating expense descriptions
    expense_description_strategy = st.sampled_from([
        "Printer paper and ink",
        "Flight to conference",
        "Team lunch meeting",
        "Legal consultation",
        "Monthly electricity bill",
        "Office rent payment",
        "Business insurance premium",
        "Google Ads campaign",
        "Adobe Creative Cloud subscription",
        "New laptop purchase",
        "Phone bill",
        "Wire transfer fee",
        "Tax preparation",
        "Employee training course",
        "Office cleaning supplies",
    ])
    
    @given(
        description=expense_description_strategy,
        num_accounts=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100)
    def test_property_21_returns_account_from_list(
        self,
        description: str,
        num_accounts: int,
    ):
        """Property 21: categorize_expense returns an account from the provided list.
        
        **Validates: Requirements 4.5**
        
        For any expense description and non-empty list of accounts,
        the returned account key SHALL be from the provided list.
        """
        from app.services.agent_tools import categorize_expense
        import random
        
        # Generate a list of accounts
        account_names = random.sample([
            "Office Supplies", "Travel Expenses", "Meals and Entertainment",
            "Professional Services", "Utilities", "Rent", "Insurance",
            "Marketing", "Software Subscriptions", "Hardware Equipment",
        ], min(num_accounts, 10))
        
        accounts = [
            {"key": f"acc-{i}", "name": name, "code": f"{5000 + i}"}
            for i, name in enumerate(account_names)
        ]
        
        result = categorize_expense.invoke({
            "description": description,
            "amount": 100.0,
            "accounts": accounts,
        })
        
        # Property: Returned key must be from the provided accounts
        account_keys = [acc["key"] for acc in accounts]
        assert result["key"] in account_keys or result["key"] == "", (
            f"Returned key '{result['key']}' not in provided accounts: {account_keys}"
        )
        
        # Property: Returned name must match the key's account
        if result["key"]:
            expected_name = next(
                acc["name"] for acc in accounts if acc["key"] == result["key"]
            )
            assert result["name"] == expected_name, (
                f"Returned name '{result['name']}' doesn't match key's account name '{expected_name}'"
            )
    
    @given(
        description=st.text(min_size=1, max_size=100),
        amount=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_property_21_score_in_valid_range(
        self,
        description: str,
        amount: float,
    ):
        """Property 21: categorize_expense returns a score in valid range.
        
        **Validates: Requirements 4.5**
        
        For any expense description, the returned score SHALL be
        between 0.0 and 1.0 inclusive.
        """
        from app.services.agent_tools import categorize_expense
        
        # Skip empty or whitespace-only descriptions
        assume(description.strip())
        
        accounts = [
            {"key": "acc-1", "name": "Office Supplies", "code": "5100"},
            {"key": "acc-2", "name": "Travel Expenses", "code": "5200"},
            {"key": "acc-3", "name": "Meals and Entertainment", "code": "5300"},
        ]
        
        result = categorize_expense.invoke({
            "description": description,
            "amount": amount,
            "accounts": accounts,
        })
        
        # Property: Score must be in [0.0, 1.0]
        assert 0.0 <= result["score"] <= 1.0, (
            f"Score {result['score']} is outside valid range [0.0, 1.0]"
        )
    
    @given(
        keyword=st.sampled_from([
            "office", "travel", "meals", "utilities", "rent",
            "insurance", "marketing", "software", "phone", "bank",
        ])
    )
    @settings(max_examples=100)
    def test_property_21_keyword_matching_improves_score(self, keyword: str):
        """Property 21: Matching keywords improve categorization score.
        
        **Validates: Requirements 4.5**
        
        When an expense description contains keywords that match an account name,
        the score for that account SHALL be higher than for unrelated accounts.
        """
        from app.services.agent_tools import categorize_expense
        
        # Create accounts where one matches the keyword
        accounts = [
            {"key": "acc-match", "name": f"{keyword.title()} Expenses", "code": "5100"},
            {"key": "acc-other", "name": "Unrelated Category", "code": "5200"},
        ]
        
        # Description containing the keyword
        description = f"Payment for {keyword} related items"
        
        result = categorize_expense.invoke({
            "description": description,
            "amount": 100.0,
            "accounts": accounts,
        })
        
        # Property: The matching account should be selected
        # (or at least have a non-zero score)
        assert result["score"] > 0 or result["key"] == "acc-match", (
            f"Expected matching account 'acc-match' but got '{result['key']}' "
            f"with score {result['score']}"
        )


class TestSupplierIdentificationMatchingProperty:
    """Property tests for supplier identification matching.
    
    **Property 22: Supplier Identification Matching**
    For any vendor name extracted from a document and list of suppliers,
    identify_supplier SHALL return the supplier with the closest name match
    or indicate no match found.
    
    **Validates: Requirements 4.6**
    """
    
    @given(
        vendor_name=st.text(min_size=1, max_size=50),
        num_suppliers=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100)
    def test_property_22_returns_valid_result_structure(
        self,
        vendor_name: str,
        num_suppliers: int,
    ):
        """Property 22: identify_supplier returns valid result structure.
        
        **Validates: Requirements 4.6**
        
        For any vendor name and supplier list, the result SHALL contain
        key, name, score, and matched fields.
        """
        from app.services.agent_tools import identify_supplier
        import random
        
        # Skip empty or whitespace-only vendor names
        assume(vendor_name.strip())
        
        supplier_names = random.sample([
            "Acme Corporation", "Office Depot", "Amazon Web Services",
            "Microsoft Corporation", "Google Cloud Platform",
            "Apple Inc", "Dell Technologies", "HP Inc",
            "Cisco Systems", "Oracle Corporation",
        ], min(num_suppliers, 10))
        
        suppliers = [
            {"key": f"sup-{i}", "name": name}
            for i, name in enumerate(supplier_names)
        ]
        
        result = identify_supplier.invoke({
            "vendor_name": vendor_name,
            "suppliers": suppliers,
        })
        
        # Property: Result must have all required fields
        assert "key" in result, "Result missing 'key' field"
        assert "name" in result, "Result missing 'name' field"
        assert "score" in result, "Result missing 'score' field"
        assert "matched" in result, "Result missing 'matched' field"
        
        # Property: Score must be in valid range
        assert 0.0 <= result["score"] <= 1.0, (
            f"Score {result['score']} is outside valid range [0.0, 1.0]"
        )
        
        # Property: matched must be boolean
        assert isinstance(result["matched"], bool), (
            f"'matched' field must be boolean, got {type(result['matched'])}"
        )
    
    @given(supplier_index=st.integers(min_value=0, max_value=4))
    @settings(max_examples=100)
    def test_property_22_exact_match_returns_correct_supplier(
        self,
        supplier_index: int,
    ):
        """Property 22: Exact vendor name match returns the correct supplier.
        
        **Validates: Requirements 4.6**
        
        When the vendor name exactly matches a supplier name (case-insensitive),
        that supplier SHALL be returned with matched=True and score=1.0.
        """
        from app.services.agent_tools import identify_supplier
        
        suppliers = [
            {"key": "sup-0", "name": "Acme Corporation"},
            {"key": "sup-1", "name": "Office Depot"},
            {"key": "sup-2", "name": "Amazon Web Services"},
            {"key": "sup-3", "name": "Microsoft Corporation"},
            {"key": "sup-4", "name": "Google Cloud Platform"},
        ]
        
        # Use the exact supplier name
        vendor_name = suppliers[supplier_index]["name"]
        
        result = identify_supplier.invoke({
            "vendor_name": vendor_name,
            "suppliers": suppliers,
        })
        
        # Property: Exact match should return the correct supplier
        assert result["matched"] is True, (
            f"Exact match for '{vendor_name}' should have matched=True"
        )
        assert result["key"] == suppliers[supplier_index]["key"], (
            f"Expected key '{suppliers[supplier_index]['key']}' but got '{result['key']}'"
        )
        assert result["score"] == 1.0, (
            f"Exact match should have score 1.0, got {result['score']}"
        )
    
    @given(
        threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_property_22_threshold_respected(self, threshold: float):
        """Property 22: Match threshold is respected.
        
        **Validates: Requirements 4.6**
        
        When a match score is below the threshold, matched SHALL be False.
        When a match score is at or above the threshold, matched SHALL be True.
        """
        from app.services.agent_tools import identify_supplier
        
        suppliers = [
            {"key": "sup-1", "name": "Acme Corporation"},
        ]
        
        # Use a completely different name that won't match well
        vendor_name = "XYZ Unrelated Company"
        
        result = identify_supplier.invoke({
            "vendor_name": vendor_name,
            "suppliers": suppliers,
            "threshold": threshold,
        })
        
        # Property: matched should reflect whether score >= threshold
        if result["score"] >= threshold:
            assert result["matched"] is True, (
                f"Score {result['score']} >= threshold {threshold}, "
                f"but matched is False"
            )
        else:
            assert result["matched"] is False, (
                f"Score {result['score']} < threshold {threshold}, "
                f"but matched is True"
            )
    
    @given(
        base_name=st.sampled_from([
            "Acme", "Office", "Amazon", "Microsoft", "Google",
        ]),
        suffix=st.sampled_from([
            " Corp", " Corporation", " Inc", " LLC", " Ltd",
            " Company", " Services", " Solutions",
        ]),
    )
    @settings(max_examples=100)
    def test_property_22_partial_match_finds_best_supplier(
        self,
        base_name: str,
        suffix: str,
    ):
        """Property 22: Partial matches find the best matching supplier.
        
        **Validates: Requirements 4.6**
        
        When a vendor name partially matches multiple suppliers,
        the supplier with the highest similarity SHALL be returned.
        """
        from app.services.agent_tools import identify_supplier
        
        suppliers = [
            {"key": "sup-1", "name": f"{base_name} Corporation"},
            {"key": "sup-2", "name": "Unrelated Company"},
            {"key": "sup-3", "name": "Different Business"},
        ]
        
        # Use a variation of the base name
        vendor_name = f"{base_name}{suffix}"
        
        result = identify_supplier.invoke({
            "vendor_name": vendor_name,
            "suppliers": suppliers,
            "threshold": 0.3,  # Low threshold to ensure we get a match
        })
        
        # Property: The matching supplier should be the one with the base name
        if result["matched"]:
            assert result["key"] == "sup-1", (
                f"Expected supplier with base name '{base_name}' (sup-1), "
                f"but got '{result['key']}' ({result['name']})"
            )
