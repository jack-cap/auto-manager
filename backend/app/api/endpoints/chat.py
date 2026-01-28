"""Chat API endpoints for the bookkeeping agent with streaming support."""

import asyncio
import json
from datetime import datetime
from typing import Annotated, AsyncGenerator, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.auth import CurrentUser
from app.core.database import get_db
from app.services.company import CompanyConfigService
from app.services.langgraph_agent import AgentEvent, BookkeeperAgent, ProcessedDocument, DocumentType
from app.services.manager_io import ManagerIOClient
from app.services.ocr import OCRService

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================


class ChatRequest(BaseModel):
    """Request body for chat messages."""
    message: str = Field(..., description="User message text")
    company_id: str = Field(..., description="Company ID for context")
    conversation_id: Optional[str] = Field(None, description="Existing conversation ID")
    confirm_submission: bool = Field(False, description="Whether to confirm pending submission")
    history: Optional[List[dict]] = Field(None, description="Conversation history [{role, content}]")


class DocumentData(BaseModel):
    """Processed document data."""
    id: str
    type: str
    filename: Optional[str] = None
    status: str
    extracted_data: Optional[dict] = None
    matched_supplier: Optional[dict] = None
    matched_account: Optional[dict] = None
    prepared_entry: Optional[dict] = None
    error: Optional[str] = None


class EventData(BaseModel):
    """Agent event for streaming."""
    type: str
    status: str
    message: str
    data: Optional[dict] = None
    timestamp: str


class ChatResponse(BaseModel):
    """Response from chat endpoint."""
    message: str = Field(..., description="Assistant response")
    conversation_id: str = Field(..., description="Conversation ID")
    documents: List[DocumentData] = Field(default_factory=list)
    events: List[EventData] = Field(default_factory=list)
    requires_confirmation: bool = Field(default=False)


class SubmitRequest(BaseModel):
    """Request to submit documents to Manager.io."""
    company_id: str = Field(..., description="Company ID")
    conversation_id: str = Field(..., description="Conversation ID with pending documents")
    confirmed: bool = Field(default=False, description="Whether user has confirmed")


class SubmitResponse(BaseModel):
    """Response from submit endpoint."""
    success: bool
    message: str
    results: List[dict] = Field(default_factory=list)


class GenerateTitleRequest(BaseModel):
    """Request to generate a chat title from conversation."""
    messages: List[dict] = Field(..., description="Conversation messages [{role, content}]")


class GenerateTitleResponse(BaseModel):
    """Response with generated title."""
    title: str


# =============================================================================
# Dependencies
# =============================================================================


async def get_company_service(
    db: AsyncSession = Depends(get_db),
) -> CompanyConfigService:
    """Get company config service."""
    return CompanyConfigService(db)


async def get_agent(
    db: AsyncSession = Depends(get_db),
) -> BookkeeperAgent:
    """Get the LangGraph agent."""
    ocr_service = OCRService()
    # Manager client will be created per-request with company credentials
    return BookkeeperAgent(ocr_service=ocr_service)


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "/message",
    response_model=ChatResponse,
    summary="Send a chat message",
    description="Send a message to the bookkeeping agent and get a response.",
)
async def send_message(
    request: ChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Send a chat message to the agent."""
    
    # Get company info
    company_service = CompanyConfigService(db)
    try:
        company = await company_service.get_by_id(request.company_id, current_user.id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Company not found: {e}")
    
    # Get reference data for matching
    try:
        api_key = company_service.decrypt_api_key(company)
        async with ManagerIOClient(base_url=company.base_url, api_key=api_key) as client:
            accounts = await client.get_chart_of_accounts()
            suppliers = await client.get_suppliers()
            
            accounts_data = [{"key": a.key, "name": a.name, "code": a.code} for a in accounts]
            suppliers_data = [{"key": s.key, "name": s.name} for s in suppliers]
    except Exception as e:
        # Continue without reference data
        accounts_data = []
        suppliers_data = []
    
    # Create agent with Manager.io client for submissions
    ocr_service = OCRService()
    manager_client = None
    if request.confirm_submission:
        try:
            api_key = company_service.decrypt_api_key(company)
            manager_client = ManagerIOClient(base_url=company.base_url, api_key=api_key)
        except Exception:
            pass
    
    agent = BookkeeperAgent(
        ocr_service=ocr_service,
        manager_client=manager_client,
    )
    
    # Process message
    response_message, events, processed_docs = await agent.process_message(
        user_id=current_user.id,
        company_id=request.company_id,
        company_name=company.name,
        message=request.message,
        conversation_id=request.conversation_id,
        accounts=accounts_data,
        suppliers=suppliers_data,
        confirm_submission=request.confirm_submission,
        history=request.history,
    )
    
    # Clean up
    if manager_client:
        await manager_client.close()
    
    # Convert to response format
    documents = [
        DocumentData(
            id=doc.id,
            type=doc.document_type.value,
            filename=doc.filename,
            status=doc.status,
            extracted_data=doc.extracted_data,
            matched_supplier=doc.matched_supplier,
            matched_account=doc.matched_account,
            prepared_entry=doc.prepared_entry,
            error=doc.error,
        )
        for doc in processed_docs
    ]
    
    event_data = [
        EventData(
            type=e.type,
            status=e.status,
            message=e.message,
            data=e.data,
            timestamp=e.timestamp,
        )
        for e in events
    ]
    
    # Check if confirmation is needed
    requires_confirmation = any(doc.status == "ready" for doc in processed_docs)
    
    return ChatResponse(
        message=response_message,
        conversation_id=request.conversation_id or "new",
        documents=documents,
        events=event_data,
        requires_confirmation=requires_confirmation,
    )


@router.post(
    "/message/stream",
    summary="Send a chat message with streaming",
    description="Send a message and receive streaming events.",
)
async def send_message_stream(
    request: ChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Send a chat message with streaming events."""
    
    # Get company info
    company_service = CompanyConfigService(db)
    try:
        company = await company_service.get_by_id(request.company_id, current_user.id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Company not found: {e}")
    
    # Create Manager.io client for tool access
    manager_client = None
    accounts_data = []
    suppliers_data = []
    
    try:
        api_key = company_service.decrypt_api_key(company)
        manager_client = ManagerIOClient(base_url=company.base_url, api_key=api_key)
        
        # Get reference data
        accounts = await manager_client.get_chart_of_accounts()
        suppliers = await manager_client.get_suppliers()
        
        accounts_data = [{"key": a.key, "name": a.name, "code": a.code} for a in accounts]
        suppliers_data = [{"key": s.key, "name": s.name} for s in suppliers]
    except Exception as e:
        # Log but continue - some tools may still work
        import logging
        logging.getLogger(__name__).warning(f"Failed to initialize Manager.io client: {e}")
    
    ocr_service = OCRService()
    agent = BookkeeperAgent(ocr_service=ocr_service, manager_client=manager_client)
    
    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events."""
        try:
            async for event in agent.stream_process(
                user_id=current_user.id,
                company_id=request.company_id,
                company_name=company.name,
                message=request.message,
                conversation_id=request.conversation_id,
                accounts=accounts_data,
                suppliers=suppliers_data,
                confirm_submission=request.confirm_submission,
                history=request.history,
            ):
                event_dict = {
                    "type": event.type,
                    "status": event.status,
                    "message": event.message,
                    "data": event.data,
                    "timestamp": event.timestamp,
                }
                yield f"data: {json.dumps(event_dict)}\n\n"
            
            yield "data: {\"type\": \"done\", \"status\": \"completed\", \"message\": \"Processing complete\"}\n\n"
        except Exception as e:
            yield f"data: {{\"type\": \"error\", \"status\": \"error\", \"message\": \"{str(e)}\"}}\n\n"
        finally:
            # Clean up manager client
            if manager_client:
                await manager_client.close()
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/upload",
    response_model=ChatResponse,
    summary="Upload documents for processing",
    description="Upload one or more documents for OCR processing and analysis.",
)
async def upload_documents(
    current_user: CurrentUser,
    company_id: Annotated[str, Form()],
    files: List[UploadFile] = File(...),
    conversation_id: Annotated[Optional[str], Form()] = None,
    message: Annotated[str, Form()] = "Please process these documents",
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Upload and process documents."""
    
    # Get company info
    company_service = CompanyConfigService(db)
    try:
        company = await company_service.get_by_id(company_id, current_user.id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Company not found: {e}")
    
    # Read file contents
    images = []
    for file in files:
        content = await file.read()
        images.append(content)
    
    # Create Manager.io client for tool access
    manager_client = None
    accounts_data = []
    suppliers_data = []
    
    try:
        api_key = company_service.decrypt_api_key(company)
        manager_client = ManagerIOClient(base_url=company.base_url, api_key=api_key)
        
        # Get reference data
        accounts = await manager_client.get_chart_of_accounts()
        suppliers = await manager_client.get_suppliers()
        
        accounts_data = [{"key": a.key, "name": a.name, "code": a.code} for a in accounts]
        suppliers_data = [{"key": s.key, "name": s.name} for s in suppliers]
    except Exception:
        pass
    
    # Create agent with manager client
    ocr_service = OCRService()
    agent = BookkeeperAgent(ocr_service=ocr_service, manager_client=manager_client)
    
    # Process with images
    response_message, events, processed_docs = await agent.process_message(
        user_id=current_user.id,
        company_id=company_id,
        company_name=company.name,
        message=message,
        conversation_id=conversation_id,
        images=images,
        accounts=accounts_data,
        suppliers=suppliers_data,
    )
    
    # Clean up
    if manager_client:
        await manager_client.close()
    
    # Convert to response format
    documents = [
        DocumentData(
            id=doc.id,
            type=doc.document_type.value,
            filename=doc.filename,
            status=doc.status,
            extracted_data=doc.extracted_data,
            matched_supplier=doc.matched_supplier,
            matched_account=doc.matched_account,
            prepared_entry=doc.prepared_entry,
            error=doc.error,
        )
        for doc in processed_docs
    ]
    
    event_data = [
        EventData(
            type=e.type,
            status=e.status,
            message=e.message,
            data=e.data,
            timestamp=e.timestamp,
        )
        for e in events
    ]
    
    requires_confirmation = any(doc.status == "ready" for doc in processed_docs)
    
    return ChatResponse(
        message=response_message,
        conversation_id=conversation_id or "new",
        documents=documents,
        events=event_data,
        requires_confirmation=requires_confirmation,
    )


@router.post(
    "/upload/stream",
    summary="Upload documents with streaming",
    description="Upload documents and receive streaming events.",
)
async def upload_documents_stream(
    current_user: CurrentUser,
    company_id: Annotated[str, Form()],
    files: List[UploadFile] = File(...),
    conversation_id: Annotated[Optional[str], Form()] = None,
    message: Annotated[str, Form()] = "Please process these documents",
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Upload documents with streaming events."""
    
    # Get company info
    company_service = CompanyConfigService(db)
    try:
        company = await company_service.get_by_id(company_id, current_user.id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Company not found: {e}")
    
    # Read file contents
    images = []
    for file in files:
        content = await file.read()
        images.append(content)
    
    # Create Manager.io client for tool access
    manager_client = None
    accounts_data = []
    suppliers_data = []
    
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        api_key = company_service.decrypt_api_key(company)
        manager_client = ManagerIOClient(base_url=company.base_url, api_key=api_key)
        
        # Get reference data
        logger.info(f"[upload_stream] Getting reference data from Manager.io")
        accounts = await manager_client.get_chart_of_accounts()
        suppliers = await manager_client.get_suppliers()
        
        accounts_data = [{"key": a.key, "name": a.name, "code": a.code} for a in accounts]
        suppliers_data = [{"key": s.key, "name": s.name} for s in suppliers]
        logger.info(f"[upload_stream] Got {len(accounts_data)} accounts, {len(suppliers_data)} suppliers")
    except Exception as e:
        logger.warning(f"[upload_stream] Failed to get reference data: {e}")
    
    ocr_service = OCRService()
    agent = BookkeeperAgent(ocr_service=ocr_service, manager_client=manager_client)
    
    logger.info(f"[upload_stream] Starting with {len(images)} images for company {company_id}")
    
    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events."""
        logger.info(f"[upload_stream] event_generator started")
        event_count = 0
        try:
            async for event in agent.stream_process(
                user_id=current_user.id,
                company_id=company_id,
                company_name=company.name,
                message=message,
                conversation_id=conversation_id,
                images=images,
                accounts=accounts_data,
                suppliers=suppliers_data,
            ):
                event_count += 1
                logger.info(f"[upload_stream] Got event #{event_count}: {event.type}/{event.status}")
                event_dict = {
                    "type": event.type,
                    "status": event.status,
                    "message": event.message,
                    "data": event.data,
                    "timestamp": event.timestamp,
                }
                yield f"data: {json.dumps(event_dict)}\n\n"
            
            logger.info(f"[upload_stream] Stream complete after {event_count} events, sending done event")
            
            # If no response event was sent, send a fallback response
            if event_count == 0:
                logger.warning(f"[upload_stream] No events received, sending fallback response")
                yield f"data: {{\"type\": \"response\", \"status\": \"completed\", \"message\": \"Response ready\", \"data\": {{\"content\": \"I received your documents but encountered an issue processing them. Please try again.\"}}, \"timestamp\": \"{datetime.now().isoformat()}\"}}\n\n"
            
            yield "data: {\"type\": \"done\", \"status\": \"completed\", \"message\": \"Processing complete\"}\n\n"
        except Exception as e:
            logger.error(f"[upload_stream] Error: {e}", exc_info=True)
            yield f"data: {{\"type\": \"error\", \"status\": \"error\", \"message\": \"{str(e)}\"}}\n\n"
            yield f"data: {{\"type\": \"response\", \"status\": \"completed\", \"message\": \"Response ready\", \"data\": {{\"content\": \"Error processing documents: {str(e)}\"}}, \"timestamp\": \"{datetime.now().isoformat()}\"}}\n\n"
            yield "data: {\"type\": \"done\", \"status\": \"completed\", \"message\": \"Processing complete\"}\n\n"
        finally:
            # Clean up manager client
            logger.info(f"[upload_stream] Cleaning up")
            if manager_client:
                await manager_client.close()
    
    logger.info(f"[upload_stream] Returning StreamingResponse")
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/submit",
    response_model=SubmitResponse,
    summary="Submit documents to Manager.io",
    description="Submit processed documents to create entries in Manager.io.",
)
async def submit_documents(
    request: SubmitRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SubmitResponse:
    """Submit processed documents to Manager.io."""
    
    if not request.confirmed:
        return SubmitResponse(
            success=False,
            message="Please confirm the submission first.",
        )
    
    # Get company info
    company_service = CompanyConfigService(db)
    try:
        company = await company_service.get_by_id(request.company_id, current_user.id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Company not found: {e}")
    
    # Create agent with Manager.io client
    try:
        api_key = company_service.decrypt_api_key(company)
        manager_client = ManagerIOClient(base_url=company.base_url, api_key=api_key)
    except Exception as e:
        return SubmitResponse(
            success=False,
            message=f"Failed to connect to Manager.io: {e}",
        )
    
    ocr_service = OCRService()
    agent = BookkeeperAgent(
        ocr_service=ocr_service,
        manager_client=manager_client,
    )
    
    # Process confirmation
    response_message, events, _ = await agent.process_message(
        user_id=current_user.id,
        company_id=request.company_id,
        company_name=company.name,
        message="yes, submit",
        conversation_id=request.conversation_id,
        confirm_submission=True,
    )
    
    await manager_client.close()
    
    # Check results from events
    submit_events = [e for e in events if e.type == "submit"]
    success = any(e.status == "completed" for e in submit_events)
    
    return SubmitResponse(
        success=success,
        message=response_message,
        results=[{"type": e.type, "status": e.status, "message": e.message} for e in submit_events],
    )


@router.post(
    "/generate-title",
    response_model=GenerateTitleResponse,
    summary="Generate chat title from conversation",
    description="Use LLM to generate a short descriptive title for a conversation.",
)
async def generate_title(
    request: GenerateTitleRequest,
    current_user: CurrentUser,
) -> GenerateTitleResponse:
    """Generate a chat title from conversation messages using LLM."""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage
    from app.core.config import settings
    
    # Build conversation summary for title generation
    conversation_text = ""
    for msg in request.messages[:10]:  # Limit to first 10 messages
        role = msg.get("role", "user")
        content = msg.get("content", "")[:200]  # Limit content length
        conversation_text += f"{role}: {content}\n"
    
    if not conversation_text.strip():
        return GenerateTitleResponse(title="New Chat")
    
    # Create LLM
    if settings.default_llm_provider == "lmstudio":
        llm = ChatOpenAI(
            base_url=settings.lmstudio_url,
            api_key="not-needed",
            model=settings.default_llm_model,
            temperature=0.3,
        )
    elif settings.default_llm_provider == "ollama":
        llm = ChatOpenAI(
            base_url=f"{settings.ollama_url}/v1",
            api_key="ollama",
            model=settings.default_llm_model,
            temperature=0.3,
        )
    else:
        llm = ChatOpenAI(
            model=settings.default_llm_model or "gpt-4",
            temperature=0.3,
        )
    
    # Generate title
    system_prompt = """Generate a short, descriptive title (3-6 words) for this conversation.
The title should capture the main topic or intent.
Respond with ONLY the title, no quotes, no explanation."""
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Conversation:\n{conversation_text}"),
        ])
        
        title = response.content.strip()
        # Strip thinking content - some models output thinking then </think> to mark the real response
        if '</think>' in title.lower():
            title = title.split('</think>')[-1]  # Take everything after </think>
        # Clean up: remove quotes, limit length
        title = title.strip().strip('"\'')[:50]
        
        if not title:
            title = "New Chat"
            
        return GenerateTitleResponse(title=title)
    except Exception as e:
        # Fallback to first user message
        for msg in request.messages:
            if msg.get("role") == "user" and msg.get("content"):
                return GenerateTitleResponse(title=msg["content"][:40])
        return GenerateTitleResponse(title="New Chat")
