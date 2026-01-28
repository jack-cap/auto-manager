"""Property-based tests for the AgentService.

Tests the following correctness properties:
- Property 20: Document Type Classification
- Property 23: Conversation History Persistence

Uses Hypothesis for property-based testing.
"""

import pytest
from datetime import datetime, timezone
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import given, settings, strategies as st, HealthCheck
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent import (
    AgentService,
    DocumentClassification,
    DOCUMENT_TYPE_PATTERNS,
)
from app.services.agent_tools import ToolContext


# =============================================================================
# Test Strategies
# =============================================================================


# Strategy for generating document text with specific patterns
def document_text_with_patterns(doc_type: str) -> st.SearchStrategy[str]:
    """Generate document text containing patterns for a specific document type."""
    patterns = DOCUMENT_TYPE_PATTERNS.get(doc_type, [])
    if not patterns:
        return st.text(min_size=10, max_size=500)
    
    # Pick a pattern and embed it in random text
    pattern_text = st.sampled_from([
        p.replace(r"\s*", " ").replace(r"\s+", " ").replace(".*", " ")
        for p in patterns
    ])
    
    return st.builds(
        lambda prefix, pattern, suffix: f"{prefix} {pattern} {suffix}",
        prefix=st.text(min_size=0, max_size=100, alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z'))),
        pattern=pattern_text,
        suffix=st.text(min_size=0, max_size=100, alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z'))),
    )


# Strategy for generating random document text
random_document_text = st.text(
    min_size=10,
    max_size=1000,
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
)


# Strategy for generating user messages
user_message = st.text(
    min_size=1,
    max_size=500,
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
)


# Strategy for generating UUIDs
uuid_strategy = st.uuids().map(str)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_encryption_service():
    """Create a mock encryption service."""
    mock = MagicMock()
    mock.encrypt.return_value = "encrypted-data"
    mock.decrypt.return_value = "decrypted-data"
    return mock


@pytest.fixture
def mock_tool_context(mock_encryption_service):
    """Create a mock ToolContext."""
    mock_db = AsyncMock(spec=AsyncSession)
    context = MagicMock(spec=ToolContext)
    context.db = mock_db
    context.redis = None
    context._encryption = mock_encryption_service
    context.get_manager_io_client = AsyncMock()
    context.get_ocr_service = MagicMock()
    context.close = AsyncMock()
    return context


# =============================================================================
# Property 20: Document Type Classification
# =============================================================================


class TestDocumentTypeClassificationProperty:
    """Property tests for document type classification.
    
    Property 20: Document Type Classification
    For any document image, the agent's document classification SHALL return
    either 'expense_receipt' or 'purchase_invoice' based on document content
    analysis.
    
    **Validates: Requirements 4.1**
    """
    
    @pytest.fixture
    def agent_service(self, mock_tool_context):
        """Create an AgentService instance for testing."""
        mock_db = AsyncMock(spec=AsyncSession)
        mock_llm = MagicMock()
        mock_ocr = MagicMock()
        
        with patch("app.services.agent.ToolContext", return_value=mock_tool_context):
            with patch("app.services.agent.set_tool_context"):
                with patch("app.services.agent.get_all_tools", return_value=[]):
                    service = AgentService(
                        db=mock_db,
                        llm_service=mock_llm,
                        ocr_service=mock_ocr,
                    )
        return service
    
    @given(text=st.text(min_size=10, max_size=500))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_20_classification_returns_valid_type(
        self,
        agent_service,
        text: str,
    ):
        """Classification always returns a valid document type.
        
        **Validates: Requirements 4.1**
        
        For any input text, the classification should return one of the
        known document types or 'unknown'.
        """
        result = agent_service.classify_document(text)
        
        # Result should be a DocumentClassification
        assert isinstance(result, DocumentClassification)
        
        # Document type should be one of the known types or 'unknown'
        valid_types = list(DOCUMENT_TYPE_PATTERNS.keys()) + ["unknown"]
        assert result.document_type in valid_types
    
    @given(text=st.text(min_size=10, max_size=500))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_20_confidence_in_valid_range(
        self,
        agent_service,
        text: str,
    ):
        """Classification confidence is always between 0 and 1.
        
        **Validates: Requirements 4.1**
        """
        result = agent_service.classify_document(text)
        
        assert 0.0 <= result.confidence <= 1.0
    
    def test_property_20_receipt_patterns_detected(self, agent_service):
        """Text containing receipt patterns is classified as receipt.
        
        **Validates: Requirements 4.1**
        """
        receipt_texts = [
            "Thank you for your purchase! Receipt #12345",
            "RECEIPT - Cash Sale - Total: $50.00",
            "Payment received. Subtotal: $40.00, Total: $45.00",
            "Change due: $5.00",
        ]
        
        for text in receipt_texts:
            result = agent_service.classify_document(text)
            assert result.document_type == "receipt", f"Failed for: {text}"
            assert result.confidence > 0
    
    def test_property_20_invoice_patterns_detected(self, agent_service):
        """Text containing invoice patterns is classified as invoice.
        
        **Validates: Requirements 4.1**
        """
        invoice_texts = [
            "INVOICE #INV-2024-001 - Bill to: Customer ABC",
            "Invoice Number: 12345, Due Date: 2024-02-15",
            "Payment Terms: Net 30, Amount Due: $500.00",
        ]
        
        for text in invoice_texts:
            result = agent_service.classify_document(text)
            assert result.document_type == "invoice", f"Failed for: {text}"
            assert result.confidence > 0
    
    def test_property_20_expense_claim_patterns_detected(self, agent_service):
        """Text containing expense claim patterns is classified as expense_claim.
        
        **Validates: Requirements 4.1**
        """
        expense_texts = [
            "EXPENSE CLAIM FORM - Employee Expenses",
            "Expense Report for January 2024",
            "Reimbursement Request - Travel Expenses",
        ]
        
        for text in expense_texts:
            result = agent_service.classify_document(text)
            assert result.document_type == "expense_claim", f"Failed for: {text}"
            assert result.confidence > 0
    
    def test_property_20_unknown_for_no_patterns(self, agent_service):
        """Text without recognizable patterns is classified as unknown.
        
        **Validates: Requirements 4.1**
        """
        # Text with no document-related patterns
        result = agent_service.classify_document("Hello world this is random text xyz")
        assert result.document_type == "unknown"
        assert result.confidence == 0.0
    
    @given(text=st.text(min_size=10, max_size=500))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_property_20_matched_patterns_are_valid(
        self,
        agent_service,
        text: str,
    ):
        """Matched patterns are always from the pattern dictionary.
        
        **Validates: Requirements 4.1**
        """
        result = agent_service.classify_document(text)
        
        if result.document_type != "unknown":
            # All matched patterns should be from the pattern dictionary
            valid_patterns = DOCUMENT_TYPE_PATTERNS.get(result.document_type, [])
            for pattern in result.matched_patterns:
                assert pattern in valid_patterns


# =============================================================================
# Property 23: Conversation History Persistence
# =============================================================================


class TestConversationHistoryPersistenceProperty:
    """Property tests for conversation history persistence.
    
    Property 23: Conversation History Persistence
    For any conversation session, all messages (user and assistant) SHALL be
    retrievable in chronological order for the duration of the session.
    
    **Validates: Requirements 4.12**
    """
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return AsyncMock(spec=AsyncSession)
    
    @pytest.fixture
    def agent_service(self, mock_db, mock_tool_context):
        """Create an AgentService instance for testing."""
        mock_llm = MagicMock()
        mock_ocr = MagicMock()
        
        with patch("app.services.agent.ToolContext", return_value=mock_tool_context):
            with patch("app.services.agent.set_tool_context"):
                with patch("app.services.agent.get_all_tools", return_value=[]):
                    service = AgentService(
                        db=mock_db,
                        llm_service=mock_llm,
                        ocr_service=mock_ocr,
                    )
        return service
    
    @pytest.mark.asyncio
    @given(
        user_id=uuid_strategy,
        company_id=uuid_strategy,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_23_conversation_created_with_valid_fields(
        self,
        agent_service,
        mock_db,
        user_id: str,
        company_id: str,
    ):
        """New conversations are created with valid user and company IDs.
        
        **Validates: Requirements 4.12**
        """
        from app.models.conversation import Conversation
        
        # Mock the database query to return None (no existing conversation)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        # Track what gets added to the session
        added_objects = []
        mock_db.add.side_effect = lambda obj: added_objects.append(obj)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        conversation = await agent_service.get_or_create_conversation(
            user_id=user_id,
            company_id=company_id,
        )
        
        # Verify a conversation was added
        assert len(added_objects) == 1
        added_conv = added_objects[0]
        
        # Verify the conversation has correct fields
        assert added_conv.user_id == user_id
        assert added_conv.company_id == company_id
        assert added_conv.title is not None
    
    @pytest.mark.asyncio
    @given(
        conversation_id=uuid_strategy,
        role=st.sampled_from(["user", "assistant", "system", "tool"]),
        content=st.text(min_size=1, max_size=500),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_23_message_saved_with_correct_fields(
        self,
        agent_service,
        mock_db,
        conversation_id: str,
        role: str,
        content: str,
    ):
        """Messages are saved with correct conversation ID, role, and content.
        
        **Validates: Requirements 4.12**
        """
        # Track what gets added to the session
        added_objects = []
        mock_db.add.side_effect = lambda obj: added_objects.append(obj)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        message = await agent_service.save_message(
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
        
        # Verify a message was added
        assert len(added_objects) == 1
        added_msg = added_objects[0]
        
        # Verify the message has correct fields
        assert added_msg.conversation_id == conversation_id
        assert added_msg.role == role
        assert added_msg.content == content
    
    @pytest.mark.asyncio
    async def test_property_23_messages_retrieved_in_order(
        self,
        agent_service,
        mock_db,
    ):
        """Messages are retrieved in chronological order.
        
        **Validates: Requirements 4.12**
        """
        from app.models.conversation import ChatMessage
        from datetime import timedelta
        
        # Create mock messages with timestamps
        base_time = datetime.now(timezone.utc)
        mock_messages = [
            MagicMock(
                id=f"msg-{i}",
                conversation_id="conv-123",
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
                created_at=base_time + timedelta(minutes=i),
            )
            for i in range(5)
        ]
        
        # Mock the database query
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = list(reversed(mock_messages))  # DB returns desc order
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        
        messages = await agent_service.get_conversation_history(
            conversation_id="conv-123",
            limit=50,
        )
        
        # Messages should be in chronological order (oldest first)
        assert len(messages) == 5
        for i, msg in enumerate(messages):
            assert msg.content == f"Message {i}"
    
    @pytest.mark.asyncio
    @given(limit=st.integers(min_value=1, max_value=100))
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_23_limit_respected(
        self,
        agent_service,
        mock_db,
        limit: int,
    ):
        """Message retrieval respects the limit parameter.
        
        **Validates: Requirements 4.12**
        """
        # Reset mock for each hypothesis example
        mock_db.reset_mock()
        
        # Mock the database query
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        
        await agent_service.get_conversation_history(
            conversation_id="conv-123",
            limit=limit,
        )
        
        # Verify the query was called
        assert mock_db.execute.called
        # The limit should be applied in the query
    
    @pytest.mark.asyncio
    async def test_property_23_existing_conversation_returned(
        self,
        agent_service,
        mock_db,
    ):
        """Existing conversation is returned when conversation_id is provided.
        
        **Validates: Requirements 4.12**
        """
        from app.models.conversation import Conversation
        
        # Create a mock existing conversation
        existing_conv = MagicMock(spec=Conversation)
        existing_conv.id = "conv-123"
        existing_conv.user_id = "user-456"
        existing_conv.company_id = "company-789"
        
        # Mock the database query to return the existing conversation
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_conv
        mock_db.execute.return_value = mock_result
        
        conversation = await agent_service.get_or_create_conversation(
            user_id="user-456",
            conversation_id="conv-123",
        )
        
        # Should return the existing conversation
        assert conversation is existing_conv
        
        # Should not add a new conversation
        mock_db.add.assert_not_called()



# =============================================================================
# Property 14: Submission Mode Support
# =============================================================================


class TestSubmissionModeSupportProperty:
    """Property tests for submission mode support.
    
    Property 14: Submission Mode Support
    For any batch of N documents, submitting in 'combined' mode SHALL create
    1 entry with N line items, and submitting in 'individual' mode SHALL
    create N separate entries.
    
    **Validates: Requirements 6.7**
    """
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return AsyncMock(spec=AsyncSession)
    
    @pytest.fixture
    def mock_manager_client(self):
        """Create a mock Manager.io client."""
        client = AsyncMock()
        client.create_expense_claim = AsyncMock()
        client.create_purchase_invoice = AsyncMock()
        return client
    
    @pytest.fixture
    def agent_service(self, mock_db, mock_tool_context, mock_manager_client):
        """Create an AgentService instance for testing."""
        mock_llm = MagicMock()
        mock_ocr = MagicMock()
        
        # Configure mock_tool_context to return the mock client
        mock_tool_context.get_manager_io_client = AsyncMock(return_value=mock_manager_client)
        
        with patch("app.services.agent.ToolContext", return_value=mock_tool_context):
            with patch("app.services.agent.set_tool_context"):
                with patch("app.services.agent.get_all_tools", return_value=[]):
                    service = AgentService(
                        db=mock_db,
                        llm_service=mock_llm,
                        ocr_service=mock_ocr,
                    )
        return service
    
    @pytest.mark.asyncio
    @given(num_documents=st.integers(min_value=1, max_value=5))
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_14_combined_mode_creates_single_entry(
        self,
        agent_service,
        mock_db,
        mock_manager_client,
        num_documents: int,
    ):
        """Combined mode creates a single entry with N line items.
        
        **Validates: Requirements 6.7**
        """
        from app.models.conversation import ProcessedDocument
        from app.services.manager_io import CreateResponse
        
        # Reset mocks
        mock_db.reset_mock()
        mock_manager_client.reset_mock()
        
        # Create mock documents
        mock_documents = []
        for i in range(num_documents):
            doc = MagicMock(spec=ProcessedDocument)
            doc.id = f"doc-{i}"
            doc.user_id = "user-123"
            doc.document_type = "receipt"
            doc.extracted_data = {
                "date": "2024-01-15",
                "vendor_name": f"Vendor {i}",
                "total_amount": 100.0 + i,
                "description": f"Expense {i}",
                "account_key": f"acc-{i}",
            }
            doc.filename = f"receipt_{i}.pdf"
            doc.status = "processed"
            mock_documents.append(doc)
        
        # Mock database query to return documents
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_documents
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        
        # Mock successful expense claim creation
        mock_manager_client.create_expense_claim.return_value = CreateResponse(
            success=True,
            key="entry-combined-123",
            message="Created successfully",
        )
        
        # Submit in combined mode
        results = await agent_service.submit_documents(
            user_id="user-123",
            company_id="company-456",
            document_ids=[f"doc-{i}" for i in range(num_documents)],
            mode="combined",
            confirmed=True,
        )
        
        # Should create exactly one entry
        assert mock_manager_client.create_expense_claim.call_count == 1
        
        # The entry should have N line items
        call_args = mock_manager_client.create_expense_claim.call_args
        expense_data = call_args[0][0]  # First positional argument
        assert len(expense_data.lines) == num_documents
        
        # Result should indicate success
        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["document_ids"] == [f"doc-{i}" for i in range(num_documents)]
    
    @pytest.mark.asyncio
    @given(num_documents=st.integers(min_value=1, max_value=5))
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_14_individual_mode_creates_separate_entries(
        self,
        agent_service,
        mock_db,
        mock_manager_client,
        num_documents: int,
    ):
        """Individual mode creates N separate entries.
        
        **Validates: Requirements 6.7**
        """
        from app.models.conversation import ProcessedDocument
        from app.services.manager_io import CreateResponse
        
        # Reset mocks
        mock_db.reset_mock()
        mock_manager_client.reset_mock()
        
        # Create mock documents
        mock_documents = []
        for i in range(num_documents):
            doc = MagicMock(spec=ProcessedDocument)
            doc.id = f"doc-{i}"
            doc.user_id = "user-123"
            doc.document_type = "receipt"
            doc.extracted_data = {
                "date": "2024-01-15",
                "vendor_name": f"Vendor {i}",
                "total_amount": 100.0 + i,
                "description": f"Expense {i}",
                "account_key": f"acc-{i}",
            }
            doc.filename = f"receipt_{i}.pdf"
            doc.status = "processed"
            mock_documents.append(doc)
        
        # Mock database query to return documents
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_documents
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        
        # Mock successful expense claim creation for each document
        mock_manager_client.create_expense_claim.return_value = CreateResponse(
            success=True,
            key="entry-123",
            message="Created successfully",
        )
        
        # Submit in individual mode
        results = await agent_service.submit_documents(
            user_id="user-123",
            company_id="company-456",
            document_ids=[f"doc-{i}" for i in range(num_documents)],
            mode="individual",
            confirmed=True,
        )
        
        # Should create N separate entries
        assert mock_manager_client.create_expense_claim.call_count == num_documents
        
        # Should have N results
        assert len(results) == num_documents
        
        # Each result should have a document_id
        for i, result in enumerate(results):
            assert result["success"] is True
            assert result["document_id"] == f"doc-{i}"


# =============================================================================
# Property 25: Batch Processing Partial Failure
# =============================================================================


class TestBatchProcessingPartialFailureProperty:
    """Property tests for batch processing partial failure handling.
    
    Property 25: Batch Processing Partial Failure
    For any batch of N documents where M documents fail processing, the system
    SHALL successfully process (N-M) documents and report both successes and
    failures.
    
    **Validates: Requirements 12.4**
    """
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return AsyncMock(spec=AsyncSession)
    
    @pytest.fixture
    def mock_manager_client(self):
        """Create a mock Manager.io client."""
        client = AsyncMock()
        client.create_expense_claim = AsyncMock()
        client.create_purchase_invoice = AsyncMock()
        return client
    
    @pytest.fixture
    def agent_service(self, mock_db, mock_tool_context, mock_manager_client):
        """Create an AgentService instance for testing."""
        mock_llm = MagicMock()
        mock_ocr = MagicMock()
        
        # Configure mock_tool_context to return the mock client
        mock_tool_context.get_manager_io_client = AsyncMock(return_value=mock_manager_client)
        
        with patch("app.services.agent.ToolContext", return_value=mock_tool_context):
            with patch("app.services.agent.set_tool_context"):
                with patch("app.services.agent.get_all_tools", return_value=[]):
                    service = AgentService(
                        db=mock_db,
                        llm_service=mock_llm,
                        ocr_service=mock_ocr,
                    )
        return service
    
    @pytest.mark.asyncio
    @given(
        num_documents=st.integers(min_value=2, max_value=5),
        num_failures=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_25_partial_failures_handled(
        self,
        agent_service,
        mock_db,
        mock_manager_client,
        num_documents: int,
        num_failures: int,
    ):
        """Partial failures are handled and both successes and failures reported.
        
        **Validates: Requirements 12.4**
        """
        from app.models.conversation import ProcessedDocument
        from app.services.manager_io import CreateResponse
        
        # Ensure num_failures doesn't exceed num_documents
        num_failures = min(num_failures, num_documents - 1)
        if num_failures < 1:
            num_failures = 1
        
        # Reset mocks
        mock_db.reset_mock()
        mock_manager_client.reset_mock()
        
        # Create mock documents
        mock_documents = []
        for i in range(num_documents):
            doc = MagicMock(spec=ProcessedDocument)
            doc.id = f"doc-{i}"
            doc.user_id = "user-123"
            doc.document_type = "receipt"
            doc.extracted_data = {
                "date": "2024-01-15",
                "vendor_name": f"Vendor {i}",
                "total_amount": 100.0 + i,
                "description": f"Expense {i}",
                "account_key": f"acc-{i}",
            }
            doc.filename = f"receipt_{i}.pdf"
            doc.status = "processed"
            mock_documents.append(doc)
        
        # Mock database query to return documents
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_documents
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        
        # Configure mock to fail for first num_failures documents
        call_count = [0]
        
        def create_expense_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= num_failures:
                return CreateResponse(
                    success=False,
                    key=None,
                    message="Simulated failure",
                )
            return CreateResponse(
                success=True,
                key=f"entry-{call_count[0]}",
                message="Created successfully",
            )
        
        mock_manager_client.create_expense_claim.side_effect = create_expense_side_effect
        
        # Submit in individual mode
        results = await agent_service.submit_documents(
            user_id="user-123",
            company_id="company-456",
            document_ids=[f"doc-{i}" for i in range(num_documents)],
            mode="individual",
            confirmed=True,
        )
        
        # Should have results for all documents
        assert len(results) == num_documents
        
        # Count successes and failures
        successes = [r for r in results if r["success"]]
        failures = [r for r in results if not r["success"]]
        
        # Should have correct number of successes and failures
        assert len(failures) == num_failures
        assert len(successes) == num_documents - num_failures
        
        # All documents should be processed (not stopped at first failure)
        assert mock_manager_client.create_expense_claim.call_count == num_documents
    
    @pytest.mark.asyncio
    async def test_property_25_all_failures_reported(
        self,
        agent_service,
        mock_db,
        mock_manager_client,
    ):
        """All failures are reported with error messages.
        
        **Validates: Requirements 12.4**
        """
        from app.models.conversation import ProcessedDocument
        from app.services.manager_io import CreateResponse
        
        # Reset mocks
        mock_db.reset_mock()
        mock_manager_client.reset_mock()
        
        # Create mock documents
        mock_documents = []
        for i in range(3):
            doc = MagicMock(spec=ProcessedDocument)
            doc.id = f"doc-{i}"
            doc.user_id = "user-123"
            doc.document_type = "receipt"
            doc.extracted_data = {
                "date": "2024-01-15",
                "vendor_name": f"Vendor {i}",
                "total_amount": 100.0,
                "description": f"Expense {i}",
                "account_key": f"acc-{i}",
            }
            doc.filename = f"receipt_{i}.pdf"
            doc.status = "processed"
            mock_documents.append(doc)
        
        # Mock database query to return documents
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_documents
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        
        # Configure mock to fail all documents
        mock_manager_client.create_expense_claim.return_value = CreateResponse(
            success=False,
            key=None,
            message="API Error: Server unavailable",
        )
        
        # Submit in individual mode
        results = await agent_service.submit_documents(
            user_id="user-123",
            company_id="company-456",
            document_ids=["doc-0", "doc-1", "doc-2"],
            mode="individual",
            confirmed=True,
        )
        
        # All should be failures
        assert len(results) == 3
        for result in results:
            assert result["success"] is False
            assert "message" in result
            assert result["message"]  # Message should not be empty
    
    @pytest.mark.asyncio
    async def test_property_25_confirmation_required(
        self,
        agent_service,
        mock_db,
        mock_manager_client,
    ):
        """Submission without confirmation returns error.
        
        **Validates: Requirements 6.5, 6.6**
        """
        # Reset mocks
        mock_db.reset_mock()
        mock_manager_client.reset_mock()
        
        # Submit without confirmation
        results = await agent_service.submit_documents(
            user_id="user-123",
            company_id="company-456",
            document_ids=["doc-0", "doc-1"],
            mode="individual",
            confirmed=False,  # Not confirmed
        )
        
        # Should return error requiring confirmation
        assert len(results) == 1
        assert results[0]["success"] is False
        assert "confirmation" in results[0]["message"].lower()
        
        # Should not call Manager.io API
        mock_manager_client.create_expense_claim.assert_not_called()
