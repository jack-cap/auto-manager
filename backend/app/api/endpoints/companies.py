"""Company configuration API endpoints."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.auth import CurrentUser, get_auth_service
from app.core.database import get_db
from app.services.company import (
    CompanyConfigService,
    CompanyConfigError,
    CompanyNotFoundError,
    CompanyValidationError,
    ManagerIOConnectionError,
)
from app.services.encryption import EncryptionError

router = APIRouter()


# Request/Response Models
class CompanyCreate(BaseModel):
    """Request body for creating a company configuration."""
    name: str
    api_key: str
    base_url: str
    
    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Company name cannot be empty")
        return v.strip()
    
    @field_validator("api_key")
    @classmethod
    def api_key_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("API key cannot be empty")
        return v.strip()
    
    @field_validator("base_url")
    @classmethod
    def base_url_valid(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Base URL cannot be empty")
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://")
        return v


class CompanyUpdate(BaseModel):
    """Request body for updating a company configuration."""
    name: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    
    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Company name cannot be empty")
        return v.strip() if v else None
    
    @field_validator("api_key")
    @classmethod
    def api_key_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("API key cannot be empty")
        return v.strip() if v else None
    
    @field_validator("base_url")
    @classmethod
    def base_url_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.strip():
                raise ValueError("Base URL cannot be empty")
            v = v.strip()
            if not v.startswith(("http://", "https://")):
                raise ValueError("Base URL must start with http:// or https://")
        return v


class CompanyResponse(BaseModel):
    """Response containing company configuration information."""
    id: str
    name: str
    base_url: str
    is_connected: bool = True
    
    model_config = {"from_attributes": True}


class CompanyListResponse(BaseModel):
    """Response containing list of company configurations."""
    companies: list[CompanyResponse]
    total: int


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


class ConnectionCheckResponse(BaseModel):
    """Response for connection check."""
    is_connected: bool
    message: str


# Dependency to get CompanyConfigService
async def get_company_service(
    db: AsyncSession = Depends(get_db),
) -> CompanyConfigService:
    """Dependency to get CompanyConfigService instance."""
    return CompanyConfigService(db)


@router.post(
    "",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new company configuration",
    description="Create a new Manager.io company configuration with API credentials.",
)
async def create_company(
    request: CompanyCreate,
    current_user: CurrentUser,
    company_service: CompanyConfigService = Depends(get_company_service),
) -> CompanyResponse:
    """Create a new company configuration.
    
    Args:
        request: Company creation data
        current_user: Current authenticated user
        company_service: Injected CompanyConfigService
        
    Returns:
        Created company information
        
    Raises:
        HTTPException: 400 if validation fails
        HTTPException: 502 if Manager.io connection fails
    """
    try:
        company = await company_service.create(
            user_id=current_user.id,
            name=request.name,
            base_url=request.base_url,
            api_key=request.api_key,
            validate_connection=True,
        )
        return CompanyResponse(
            id=company.id,
            name=company.name,
            base_url=company.base_url,
            is_connected=True,
        )
    except CompanyValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ManagerIOConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )
    except EncryptionError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Encryption error: {e}",
        )
    except CompanyConfigError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "",
    response_model=CompanyListResponse,
    summary="List all company configurations",
    description="Get all company configurations for the current user.",
)
async def list_companies(
    current_user: CurrentUser,
    company_service: CompanyConfigService = Depends(get_company_service),
) -> CompanyListResponse:
    """List all company configurations for the current user.
    
    Args:
        current_user: Current authenticated user
        company_service: Injected CompanyConfigService
        
    Returns:
        List of company configurations with connection status
    """
    companies = await company_service.get_all_for_user(current_user.id)
    
    # Check connection status for each company
    company_responses = []
    for c in companies:
        is_connected = await company_service.check_connection(c.id, current_user.id)
        company_responses.append(
            CompanyResponse(
                id=c.id,
                name=c.name,
                base_url=c.base_url,
                is_connected=is_connected,
            )
        )
    
    return CompanyListResponse(
        companies=company_responses,
        total=len(companies),
    )


@router.get(
    "/{company_id}",
    response_model=CompanyResponse,
    summary="Get a company configuration",
    description="Get a specific company configuration by ID.",
)
async def get_company(
    company_id: str,
    current_user: CurrentUser,
    company_service: CompanyConfigService = Depends(get_company_service),
) -> CompanyResponse:
    """Get a company configuration by ID.
    
    Args:
        company_id: ID of the company to retrieve
        current_user: Current authenticated user
        company_service: Injected CompanyConfigService
        
    Returns:
        Company configuration information
        
    Raises:
        HTTPException: 404 if company not found
    """
    try:
        company = await company_service.get_by_id(company_id, current_user.id)
        return CompanyResponse(
            id=company.id,
            name=company.name,
            base_url=company.base_url,
            is_connected=True,
        )
    except CompanyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.put(
    "/{company_id}",
    response_model=CompanyResponse,
    summary="Update a company configuration",
    description="Update an existing company configuration.",
)
async def update_company(
    company_id: str,
    request: CompanyUpdate,
    current_user: CurrentUser,
    company_service: CompanyConfigService = Depends(get_company_service),
) -> CompanyResponse:
    """Update a company configuration.
    
    Args:
        company_id: ID of the company to update
        request: Company update data
        current_user: Current authenticated user
        company_service: Injected CompanyConfigService
        
    Returns:
        Updated company information
        
    Raises:
        HTTPException: 404 if company not found
        HTTPException: 400 if validation fails
        HTTPException: 502 if Manager.io connection fails
    """
    try:
        company = await company_service.update(
            company_id=company_id,
            user_id=current_user.id,
            name=request.name,
            base_url=request.base_url,
            api_key=request.api_key,
            validate_connection=True,
        )
        return CompanyResponse(
            id=company.id,
            name=company.name,
            base_url=company.base_url,
            is_connected=True,
        )
    except CompanyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except CompanyValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ManagerIOConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )
    except EncryptionError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Encryption error: {e}",
        )
    except CompanyConfigError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete(
    "/{company_id}",
    response_model=MessageResponse,
    summary="Delete a company configuration",
    description="Delete a company configuration and associated cached data.",
)
async def delete_company(
    company_id: str,
    current_user: CurrentUser,
    company_service: CompanyConfigService = Depends(get_company_service),
) -> MessageResponse:
    """Delete a company configuration.
    
    Args:
        company_id: ID of the company to delete
        current_user: Current authenticated user
        company_service: Injected CompanyConfigService
        
    Returns:
        Success message
        
    Raises:
        HTTPException: 404 if company not found
    """
    try:
        await company_service.delete(company_id, current_user.id)
        return MessageResponse(message="Company configuration deleted successfully")
    except CompanyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.post(
    "/{company_id}/check-connection",
    response_model=ConnectionCheckResponse,
    summary="Check Manager.io connection",
    description="Verify that the Manager.io API connection is working.",
)
async def check_connection(
    company_id: str,
    current_user: CurrentUser,
    company_service: CompanyConfigService = Depends(get_company_service),
) -> ConnectionCheckResponse:
    """Check Manager.io API connection for a company.
    
    Args:
        company_id: ID of the company to check
        current_user: Current authenticated user
        company_service: Injected CompanyConfigService
        
    Returns:
        Connection status
        
    Raises:
        HTTPException: 404 if company not found
    """
    try:
        company = await company_service.get_by_id(company_id, current_user.id)
        is_connected = await company_service.check_connection(
            company_id, current_user.id
        )
        
        if is_connected:
            return ConnectionCheckResponse(
                is_connected=True,
                message="Successfully connected to Manager.io",
            )
        else:
            return ConnectionCheckResponse(
                is_connected=False,
                message="Failed to connect to Manager.io. Please check your credentials.",
            )
    except CompanyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
