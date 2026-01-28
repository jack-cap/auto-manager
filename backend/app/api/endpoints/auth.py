"""Authentication API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.auth import AuthenticationError, AuthService

router = APIRouter()

# Security scheme for JWT bearer tokens
security = HTTPBearer()


# Request/Response Models
class RegisterRequest(BaseModel):
    """Request body for user registration."""
    email: EmailStr
    password: str
    name: str


class LoginRequest(BaseModel):
    """Request body for user login."""
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Request body for token refresh."""
    refresh_token: str


class TokenResponse(BaseModel):
    """Response containing JWT tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    """Response containing user information."""
    id: str
    email: str
    name: str
    
    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


# Dependency to get AuthService
async def get_auth_service(
    db: AsyncSession = Depends(get_db),
) -> AuthService:
    """Dependency to get AuthService instance."""
    return AuthService(db)


# Dependency to get current user from token
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Dependency to get current authenticated user.
    
    Extracts and validates JWT token from Authorization header.
    """
    try:
        user = await auth_service.get_current_user(credentials.credentials)
        return UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
        )
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


# Type alias for current user dependency
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a new user account with email, password, and name.",
)
async def register(
    request: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Register a new user.
    
    Args:
        request: Registration data with email, password, and name
        auth_service: Injected AuthService
        
    Returns:
        Created user information
        
    Raises:
        HTTPException: 400 if email already exists
    """
    try:
        user = await auth_service.register(
            email=request.email,
            password=request.password,
            name=request.name,
        )
        return UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
        )
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login user",
    description="Authenticate user with email and password, returns JWT tokens.",
)
async def login(
    request: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Login user and return tokens.
    
    Args:
        request: Login credentials with email and password
        auth_service: Injected AuthService
        
    Returns:
        JWT access and refresh tokens
        
    Raises:
        HTTPException: 401 if credentials are invalid
    """
    try:
        token_pair = await auth_service.login(
            email=request.email,
            password=request.password,
        )
        return TokenResponse(
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            token_type=token_pair.token_type,
            expires_in=token_pair.expires_in,
        )
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Get new access and refresh tokens using a valid refresh token.",
)
async def refresh(
    request: RefreshRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Refresh access token.
    
    Args:
        request: Refresh token
        auth_service: Injected AuthService
        
    Returns:
        New JWT access and refresh tokens
        
    Raises:
        HTTPException: 401 if refresh token is invalid or expired
    """
    try:
        token_pair = await auth_service.refresh_token(request.refresh_token)
        return TokenResponse(
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            token_type=token_pair.token_type,
            expires_in=token_pair.expires_in,
        )
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout user",
    description="Invalidate all sessions for the current user.",
)
async def logout(
    current_user: CurrentUser,
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    """Logout user and invalidate all sessions.
    
    Args:
        current_user: Current authenticated user
        auth_service: Injected AuthService
        
    Returns:
        Success message
    """
    await auth_service.logout(current_user.id)
    return MessageResponse(message="Successfully logged out")


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Get information about the currently authenticated user.",
)
async def get_me(current_user: CurrentUser) -> UserResponse:
    """Get current user information.
    
    Args:
        current_user: Current authenticated user
        
    Returns:
        User information
    """
    return current_user
