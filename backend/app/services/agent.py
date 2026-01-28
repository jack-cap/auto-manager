"""LangChain Agent Service for bookkeeping automation.

This module provides the main agent service that orchestrates:
- Document processing and classification
- Conversation management
- Tool execution for Manager.io operations
- Submission workflows with confirmation

The agent uses LangChain for tool binding and orchestration, with
LiteLLM for flexible model routing to local or cloud LLM providers.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import ChatMessage, Conversation, ProcessedDocument
from app.services.agent_tools import (
    ToolContext,
    get_all_tools,
    set_tool_context,
)
from app.services.llm import LLMService
from app.services.manager_io import (
    ExpenseClaimData,
    ExpenseClaimLine,
    PurchaseInvoiceData,
    PurchaseInvoiceLine,
)
from app.services.ocr import OCRService

logger = logging.getLogger(__name__)


# Document type classification patterns
DOCUMENT_TYPE_PATTERNS = {
    "receipt": [
        r"receipt",
        r"cash\s*sale",
        r"payment\s*received",
        r"thank\s*you\s*for\s*your\s*purchase",
        r"subtotal.*total",
        r"change\s*due",
    ],
    "invoice": [
        r"invoice",
        r"bill\s*to",
        r"due\s*date",
        r"payment\s*terms",
        r"invoice\s*number",
        r"inv\s*#",
        r"amount\s*due",
    ],
    "expense_claim": [
        r"expense\s*claim",
        r"expense\s*report",
        r"reimbursement",
        r"claim\s*form",
        r"employee\s*expenses",
    ],
    "bank_statement": [
        r"bank\s*statement",
        r"account\s*statement",
        r"opening\s*balance",
        r"closing\s*balance",
        r"transaction\s*history",
    ],
}


SYSTEM_PROMPT = """You are an AI bookkeeping assistant for Manager.io accounting software.

Your role is to help users:
1. Process financial documents (receipts, invoices, expense claims)
2. Extract and categorize expense data
3. Match vendors to existing suppliers
4. Create entries in Manager.io (expense claims, purchase invoices)
5. Answer questions about their financial data

When processing documents:
- First extract text using OCR if an image is provided
- Classify the document type (receipt, invoice, expense claim)
- Extract key information: date, vendor, amount, description, line items
- Match the vendor to existing suppliers
- Categorize expenses to appropriate accounts
- Present the extracted data for user confirmation before submission

Always confirm with the user before submitting entries to Manager.io.
Be helpful, accurate, and explain your reasoning when categorizing expenses.

Current company context: {company_name}
"""


class DocumentClassification(BaseModel):
    """Result of document type classification."""
    
    document_type: str = Field(description="Classified document type")
    confidence: float = Field(description="Classification confidence (0-1)")
    matched_patterns: List[str] = Field(default_factory=list)


class ExtractedDocumentData(BaseModel):
    """Structured data extracted from a document."""
    
    document_type: str
    date: Optional[str] = None
    vendor_name: Optional[str] = None
    total_amount: Optional[float] = None
    currency: str = "USD"
    description: Optional[str] = None
    reference: Optional[str] = None
    line_items: List[Dict[str, Any]] = Field(default_factory=list)
    raw_text: str = ""


class AgentResponse(BaseModel):
    """Response from the agent."""
    
    message: str
    documents: List[Dict[str, Any]] = Field(default_factory=list)
    requires_confirmation: bool = False
    pending_submission: Optional[Dict[str, Any]] = None


class AgentService:
    """Service for managing the LangChain bookkeeping agent.
    
    Handles:
    - Conversation management and history
    - Document processing pipeline
    - Tool execution with LangChain bindings
    - Submission workflows with combined/individual modes
    
    The agent uses LangChain for tool orchestration and LiteLLM for
    flexible model routing to local (Ollama/LMStudio) or cloud providers.
    
    Example:
        ```python
        agent = AgentService(
            db=db_session,
            llm_service=llm_service,
            ocr_service=ocr_service,
        )
        
        response = await agent.process_message(
            user_id="user-123",
            company_id="company-456",
            message="Process this receipt",
            attachments=[image_bytes],
        )
        ```
    """
    
    def __init__(
        self,
        db: AsyncSession,
        llm_service: LLMService,
        ocr_service: Optional[OCRService] = None,
        redis: Optional[Redis] = None,
    ):
        """Initialize the agent service.
        
        Args:
            db: Database session for conversation persistence
            llm_service: LLM service for chat completions
            ocr_service: OCR service for document text extraction
            redis: Redis client for caching
        """
        self.db = db
        self.llm_service = llm_service
        self.ocr_service = ocr_service or OCRService()
        self.redis = redis
        
        # Initialize tool context
        self._tool_context = ToolContext(
            db=db,
            redis=redis,
            ocr_service=self.ocr_service,
        )
        set_tool_context(self._tool_context)
        
        # Get all tools for agent binding
        self._tools = get_all_tools()
        
        # Build tool name to function mapping for execution
        self._tool_map = {tool.name: tool for tool in self._tools}
    
    def get_registered_tools(self) -> List[str]:
        """Get list of registered tool names.
        
        Returns:
            List of tool names available to the agent
        """
        return list(self._tool_map.keys())
    
    def classify_document(self, text: str) -> DocumentClassification:
        """Classify document type based on text content.
        
        Args:
            text: Extracted text from the document
            
        Returns:
            DocumentClassification with type and confidence
        """
        text_lower = text.lower()
        scores: Dict[str, Tuple[float, List[str]]] = {}
        
        for doc_type, patterns in DOCUMENT_TYPE_PATTERNS.items():
            matched = []
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    matched.append(pattern)
            
            if matched:
                # Score based on number of matched patterns
                score = len(matched) / len(patterns)
                scores[doc_type] = (score, matched)
        
        if not scores:
            return DocumentClassification(
                document_type="unknown",
                confidence=0.0,
                matched_patterns=[],
            )
        
        # Get highest scoring type
        best_type = max(scores.keys(), key=lambda k: scores[k][0])
        best_score, matched_patterns = scores[best_type]
        
        return DocumentClassification(
            document_type=best_type,
            confidence=min(best_score, 1.0),
            matched_patterns=matched_patterns,
        )
    
    async def get_or_create_conversation(
        self,
        user_id: str,
        company_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Conversation:
        """Get existing conversation or create a new one.
        
        Args:
            user_id: User ID
            company_id: Optional company context
            conversation_id: Optional existing conversation ID
            
        Returns:
            Conversation instance
        """
        if conversation_id:
            result = await self.db.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
            conversation = result.scalar_one_or_none()
            if conversation:
                return conversation
        
        # Create new conversation
        conversation = Conversation(
            user_id=user_id,
            company_id=company_id,
            title=f"Conversation {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        )
        self.db.add(conversation)
        await self.db.flush()
        await self.db.refresh(conversation)
        
        return conversation
    
    async def get_conversation_history(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> List[ChatMessage]:
        """Get conversation history.
        
        Args:
            conversation_id: Conversation ID
            limit: Maximum messages to return
            
        Returns:
            List of ChatMessage instances
        """
        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        messages = result.scalars().all()
        return list(reversed(messages))
    
    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: Optional[str],
        tool_calls: Optional[List[Dict]] = None,
        tool_call_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> ChatMessage:
        """Save a message to conversation history.
        
        Args:
            conversation_id: Conversation ID
            role: Message role (user, assistant, system, tool)
            content: Message content
            tool_calls: Tool calls for assistant messages
            tool_call_id: Tool call ID for tool response messages
            metadata: Additional metadata
            
        Returns:
            Created ChatMessage instance
        """
        message = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            metadata=metadata or {},
        )
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)
        return message
    
    async def process_document(
        self,
        user_id: str,
        company_id: str,
        image_data: bytes,
        filename: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> ProcessedDocument:
        """Process a document through OCR and extraction.
        
        Args:
            user_id: User ID
            company_id: Company ID for context
            image_data: Raw image/PDF bytes
            filename: Original filename
            conversation_id: Optional conversation to associate with
            
        Returns:
            ProcessedDocument with extracted data
        """
        logger.info(f"Processing document for user {user_id}, company {company_id}")
        
        # Create document record
        doc = ProcessedDocument(
            user_id=user_id,
            company_id=company_id,
            conversation_id=conversation_id,
            filename=filename,
            status="pending",
        )
        self.db.add(doc)
        await self.db.flush()
        
        try:
            # Extract text via OCR
            is_pdf = image_data[:4] == b'%PDF'
            if is_pdf:
                ocr_result = await self.ocr_service.extract_from_pdf(image_data)
            else:
                ocr_result = await self.ocr_service.extract_text(image_data)
            
            if not ocr_result.success:
                doc.status = "error"
                doc.error_message = ocr_result.error
                await self.db.flush()
                return doc
            
            doc.extracted_text = ocr_result.text
            
            # Classify document type
            classification = self.classify_document(ocr_result.text)
            doc.document_type = classification.document_type
            
            # Use LLM to extract structured data
            extracted_data = await self._extract_structured_data(
                ocr_result.text,
                classification.document_type,
                company_id,
                user_id,
            )
            
            doc.extracted_data = extracted_data
            doc.status = "processed"
            
            await self.db.flush()
            await self.db.refresh(doc)
            
            logger.info(f"Document processed successfully: {doc.id}, type: {doc.document_type}")
            return doc
            
        except Exception as e:
            logger.error(f"Error processing document: {e}")
            doc.status = "error"
            doc.error_message = str(e)
            await self.db.flush()
            return doc
    
    async def _extract_structured_data(
        self,
        text: str,
        document_type: str,
        company_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """Use LLM to extract structured data from document text.
        
        Args:
            text: OCR extracted text
            document_type: Classified document type
            company_id: Company ID for context
            user_id: User ID
            
        Returns:
            Dictionary of extracted structured data
        """
        extraction_prompt = f"""Extract structured data from this {document_type} document.

Document text:
{text}

Extract and return a JSON object with these fields (use null for missing values):
- date: Date in YYYY-MM-DD format
- vendor_name: Name of the vendor/supplier
- total_amount: Total amount as a number
- currency: Currency code (default USD)
- description: Brief description
- reference: Invoice/receipt number if present
- line_items: Array of items with description, quantity, unit_price, amount

Return ONLY the JSON object, no other text."""

        try:
            from app.services.llm import Message
            response = await self.llm_service.chat([
                Message(role="system", content="You are a data extraction assistant. Extract structured data from documents and return valid JSON only."),
                Message(role="user", content=extraction_prompt),
            ])
            
            # Parse JSON from response
            import json
            # Try to extract JSON from the response
            content = response
            # Find JSON in response
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                return json.loads(json_match.group())
            
            return {"raw_response": content}
            
        except Exception as e:
            logger.error(f"Error extracting structured data: {e}")
            return {"error": str(e)}
    
    async def process_message(
        self,
        user_id: str,
        company_id: str,
        message: str,
        conversation_id: Optional[str] = None,
        attachments: Optional[List[bytes]] = None,
    ) -> AgentResponse:
        """Process a user message and generate a response.
        
        Args:
            user_id: User ID
            company_id: Company ID for context
            message: User message text
            conversation_id: Optional existing conversation ID
            attachments: Optional list of document attachments (images/PDFs)
            
        Returns:
            AgentResponse with message and any processed documents
        """
        logger.info(f"Processing message for user {user_id}, company {company_id}")
        
        # Get or create conversation
        conversation = await self.get_or_create_conversation(
            user_id=user_id,
            company_id=company_id,
            conversation_id=conversation_id,
        )
        
        # Save user message
        await self.save_message(
            conversation_id=conversation.id,
            role="user",
            content=message,
        )
        
        # Process any attachments
        processed_docs = []
        if attachments:
            for i, attachment in enumerate(attachments):
                doc = await self.process_document(
                    user_id=user_id,
                    company_id=company_id,
                    image_data=attachment,
                    filename=f"attachment_{i+1}",
                    conversation_id=conversation.id,
                )
                if doc.status == "processed":
                    processed_docs.append({
                        "id": doc.id,
                        "type": doc.document_type,
                        "data": doc.extracted_data,
                        "filename": doc.filename,
                    })
        
        # Get conversation history
        history = await self.get_conversation_history(conversation.id)
        
        # Build messages for LLM
        from app.services.llm import Message
        llm_messages = [
            Message(role="system", content=SYSTEM_PROMPT.format(company_name=company_id)),
        ]
        
        for msg in history[-10:]:  # Last 10 messages for context
            llm_messages.append(Message(role=msg.role, content=msg.content or ""))
        
        # Add document context if any
        if processed_docs:
            doc_context = "I've processed the following documents:\n"
            for doc in processed_docs:
                doc_context += f"\n{doc['type'].upper()}: {doc['filename']}\n"
                doc_context += f"Extracted data: {doc['data']}\n"
            llm_messages.append(Message(role="system", content=doc_context))
        
        # Generate response
        try:
            response_text = await self.llm_service.chat(llm_messages)
            
            # Save assistant response
            await self.save_message(
                conversation_id=conversation.id,
                role="assistant",
                content=response_text,
            )
            
            # Check if response requires confirmation for submission
            requires_confirmation = any(
                phrase in response_text.lower()
                for phrase in ["submit", "create entry", "post to manager", "confirm"]
            )
            
            return AgentResponse(
                message=response_text,
                documents=processed_docs,
                requires_confirmation=requires_confirmation,
            )
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            error_message = f"I encountered an error processing your request: {str(e)}"
            
            await self.save_message(
                conversation_id=conversation.id,
                role="assistant",
                content=error_message,
            )
            
            return AgentResponse(
                message=error_message,
                documents=processed_docs,
            )
    
    async def submit_documents(
        self,
        user_id: str,
        company_id: str,
        document_ids: List[str],
        mode: Literal["individual", "combined"] = "individual",
        confirmed: bool = False,
    ) -> List[Dict[str, Any]]:
        """Submit processed documents to Manager.io.
        
        Supports two submission modes:
        - "individual": Each document creates a separate entry in Manager.io
        - "combined": All documents are combined into a single entry with multiple lines
        
        Handles partial failures gracefully - if some documents fail, others
        will still be submitted and the failures will be reported.
        
        Args:
            user_id: User ID
            company_id: Company ID
            document_ids: List of ProcessedDocument IDs to submit
            mode: "individual" submits each separately, "combined" creates one entry
            confirmed: Whether user has confirmed the submission
            
        Returns:
            List of submission results, each containing:
            - success: Whether submission was successful
            - key: Manager.io entry key if successful
            - message: Success or error message
            - document_id: Document ID (for individual mode)
            - document_ids: Document IDs (for combined mode)
            
        Raises:
            ValueError: If no valid documents found or mode is invalid
        """
        logger.info(f"Submitting {len(document_ids)} documents, mode={mode}, confirmed={confirmed}")
        
        if not confirmed:
            return [{
                "success": False,
                "message": "Submission requires confirmation. Please confirm before submitting.",
                "requires_confirmation": True,
            }]
        
        if mode not in ("individual", "combined"):
            return [{
                "success": False,
                "message": f"Invalid submission mode: {mode}. Use 'individual' or 'combined'.",
            }]
        
        results: List[Dict[str, Any]] = []
        
        # Fetch documents
        result = await self.db.execute(
            select(ProcessedDocument).where(
                ProcessedDocument.id.in_(document_ids),
                ProcessedDocument.user_id == user_id,
                ProcessedDocument.status == "processed",
            )
        )
        documents = list(result.scalars().all())
        
        if not documents:
            return [{"success": False, "message": "No valid documents found for submission"}]
        
        # Get Manager.io client
        try:
            client = await self._tool_context.get_manager_io_client(company_id, user_id)
        except Exception as e:
            logger.error(f"Failed to get Manager.io client: {e}")
            return [{"success": False, "message": f"Failed to connect to Manager.io: {e}"}]
        
        if mode == "combined":
            results = await self._submit_combined(documents, client, user_id)
        else:
            results = await self._submit_individual(documents, client, user_id)
        
        await self.db.flush()
        
        return results
    
    async def _submit_combined(
        self,
        documents: List[ProcessedDocument],
        client: Any,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """Submit documents as a single combined entry.
        
        Creates one expense claim with multiple line items, one per document.
        
        Args:
            documents: List of ProcessedDocument instances
            client: ManagerIOClient instance
            user_id: User ID for PaidBy field
            
        Returns:
            List with single submission result
        """
        # Build combined line items
        lines = []
        for doc in documents:
            data = doc.extracted_data or {}
            line = ExpenseClaimLine(
                account=data.get("account_key", ""),
                line_description=data.get("description", doc.filename or "Expense"),
                qty=1,
                purchase_unit_price=float(data.get("total_amount", 0)),
            )
            lines.append(line)
        
        # Get date from first document or use today
        first_data = documents[0].extracted_data or {}
        claim_date = first_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        
        try:
            expense_data = ExpenseClaimData(
                date=claim_date,
                paid_by=user_id,
                payee=first_data.get("vendor_name", "Various"),
                description=f"Combined expense claim ({len(documents)} items)",
                lines=lines,
                has_line_description=True,
            )
            
            response = await client.create_expense_claim(expense_data)
            
            if response.success:
                # Update all documents
                for doc in documents:
                    doc.status = "submitted"
                    doc.submission_key = response.key
                
                return [{
                    "success": True,
                    "key": response.key,
                    "message": f"Combined expense claim created with {len(documents)} items",
                    "document_ids": [d.id for d in documents],
                }]
            else:
                return [{
                    "success": False,
                    "message": response.message or "Failed to create combined expense claim",
                    "document_ids": [d.id for d in documents],
                }]
                
        except Exception as e:
            logger.error(f"Error submitting combined documents: {e}")
            return [{
                "success": False,
                "message": str(e),
                "document_ids": [d.id for d in documents],
            }]
    
    async def _submit_individual(
        self,
        documents: List[ProcessedDocument],
        client: Any,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """Submit each document as a separate entry.
        
        Handles partial failures - continues processing remaining documents
        even if some fail.
        
        Args:
            documents: List of ProcessedDocument instances
            client: ManagerIOClient instance
            user_id: User ID for PaidBy field
            
        Returns:
            List of submission results, one per document
        """
        results: List[Dict[str, Any]] = []
        
        for doc in documents:
            try:
                data = doc.extracted_data or {}
                doc_type = doc.document_type or "expense_claim"
                
                if doc_type in ("receipt", "expense_claim", "expense"):
                    # Create expense claim
                    line = ExpenseClaimLine(
                        account=data.get("account_key", ""),
                        line_description=data.get("description", doc.filename or "Expense"),
                        qty=1,
                        purchase_unit_price=float(data.get("total_amount", 0)),
                    )
                    
                    expense_data = ExpenseClaimData(
                        date=data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                        paid_by=user_id,
                        payee=data.get("vendor_name", "Unknown"),
                        description=data.get("description", doc.filename or "Expense"),
                        lines=[line],
                        has_line_description=True,
                    )
                    
                    response = await client.create_expense_claim(expense_data)
                    
                elif doc_type == "invoice":
                    # Create purchase invoice
                    line = PurchaseInvoiceLine(
                        account=data.get("account_key", ""),
                        line_description=data.get("description", ""),
                        purchase_unit_price=float(data.get("total_amount", 0)),
                    )
                    
                    invoice_data = PurchaseInvoiceData(
                        issue_date=data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                        reference=data.get("reference", doc.filename or ""),
                        description=data.get("description", ""),
                        supplier=data.get("supplier_key", ""),
                        lines=[line],
                        has_line_number=True,
                        has_line_description=True,
                    )
                    
                    response = await client.create_purchase_invoice(invoice_data)
                    
                else:
                    # Unknown document type
                    results.append({
                        "success": False,
                        "message": f"Unknown document type: {doc_type}",
                        "document_id": doc.id,
                    })
                    continue
                
                if response.success:
                    doc.status = "submitted"
                    doc.submission_key = response.key
                    
                    results.append({
                        "success": True,
                        "key": response.key,
                        "message": f"{doc_type.replace('_', ' ').title()} submitted successfully",
                        "document_id": doc.id,
                    })
                else:
                    doc.status = "error"
                    doc.error_message = response.message
                    
                    results.append({
                        "success": False,
                        "message": response.message or f"Failed to submit {doc_type}",
                        "document_id": doc.id,
                    })
                    
            except Exception as e:
                logger.error(f"Error submitting document {doc.id}: {e}")
                doc.status = "error"
                doc.error_message = str(e)
                
                results.append({
                    "success": False,
                    "message": str(e),
                    "document_id": doc.id,
                })
        
        return results
    
    async def close(self) -> None:
        """Clean up resources."""
        await self._tool_context.close()
