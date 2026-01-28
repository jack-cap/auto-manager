"""Comprehensive error handling with suggested actions.

This module provides standardized error responses with actionable suggestions
for users to resolve issues.

Validates: Requirements 12.1, 12.2, 12.3
"""

from enum import Enum
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel


class ErrorCode(str, Enum):
    """Standardized error codes for the application."""
    
    # Authentication errors
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    AUTH_TOKEN_INVALID = "AUTH_TOKEN_INVALID"
    AUTH_UNAUTHORIZED = "AUTH_UNAUTHORIZED"
    
    # Company errors
    COMPANY_NOT_FOUND = "COMPANY_NOT_FOUND"
    COMPANY_API_KEY_INVALID = "COMPANY_API_KEY_INVALID"
    COMPANY_CONNECTION_FAILED = "COMPANY_CONNECTION_FAILED"
    
    # Manager.io API errors
    MANAGER_IO_CONNECTION_ERROR = "MANAGER_IO_CONNECTION_ERROR"
    MANAGER_IO_AUTH_ERROR = "MANAGER_IO_AUTH_ERROR"
    MANAGER_IO_NOT_FOUND = "MANAGER_IO_NOT_FOUND"
    MANAGER_IO_VALIDATION_ERROR = "MANAGER_IO_VALIDATION_ERROR"
    MANAGER_IO_RATE_LIMITED = "MANAGER_IO_RATE_LIMITED"
    MANAGER_IO_SERVER_ERROR = "MANAGER_IO_SERVER_ERROR"
    
    # OCR errors
    OCR_CONNECTION_ERROR = "OCR_CONNECTION_ERROR"
    OCR_MODEL_NOT_FOUND = "OCR_MODEL_NOT_FOUND"
    OCR_PROCESSING_ERROR = "OCR_PROCESSING_ERROR"
    OCR_TIMEOUT = "OCR_TIMEOUT"
    
    # LLM errors
    LLM_CONNECTION_ERROR = "LLM_CONNECTION_ERROR"
    LLM_MODEL_NOT_FOUND = "LLM_MODEL_NOT_FOUND"
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    
    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_JSON = "INVALID_JSON"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    
    # Network errors
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    
    # General errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"


class ErrorResponse(BaseModel):
    """Standardized error response format.
    
    Attributes:
        error: Short error description
        error_code: Machine-readable error code
        message: Human-readable error message
        details: Additional error details
        retry_after: Seconds to wait before retrying (for rate limits)
        suggested_action: Actionable suggestion for the user
        is_retryable: Whether the operation can be retried
    """
    error: str
    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    retry_after: Optional[int] = None
    suggested_action: Optional[str] = None
    is_retryable: bool = False


# Suggested actions for common errors
SUGGESTED_ACTIONS = {
    ErrorCode.AUTH_INVALID_CREDENTIALS: "Please check your email and password and try again.",
    ErrorCode.AUTH_TOKEN_EXPIRED: "Your session has expired. Please log in again.",
    ErrorCode.AUTH_TOKEN_INVALID: "Your session is invalid. Please log in again.",
    ErrorCode.AUTH_UNAUTHORIZED: "You don't have permission to perform this action.",
    
    ErrorCode.COMPANY_NOT_FOUND: "The company was not found. Please select a different company.",
    ErrorCode.COMPANY_API_KEY_INVALID: "The API key is invalid. Please update your company configuration.",
    ErrorCode.COMPANY_CONNECTION_FAILED: "Could not connect to Manager.io. Please verify the base URL and API key.",
    
    ErrorCode.MANAGER_IO_CONNECTION_ERROR: "Cannot connect to Manager.io. Please check that the server is running and accessible.",
    ErrorCode.MANAGER_IO_AUTH_ERROR: "Manager.io authentication failed. Please verify your API key in company settings.",
    ErrorCode.MANAGER_IO_NOT_FOUND: "The requested resource was not found in Manager.io.",
    ErrorCode.MANAGER_IO_VALIDATION_ERROR: "The data submitted to Manager.io was invalid. Please review and correct the entries.",
    ErrorCode.MANAGER_IO_RATE_LIMITED: "Too many requests to Manager.io. Please wait a moment and try again.",
    ErrorCode.MANAGER_IO_SERVER_ERROR: "Manager.io server error. Please try again later or contact support.",
    
    ErrorCode.OCR_CONNECTION_ERROR: "Cannot connect to LMStudio for OCR. Please ensure LMStudio is running at the configured URL.",
    ErrorCode.OCR_MODEL_NOT_FOUND: "The OCR model (chandra) is not loaded. Please load the model in LMStudio.",
    ErrorCode.OCR_PROCESSING_ERROR: "Failed to process the document. Please try uploading a clearer image.",
    ErrorCode.OCR_TIMEOUT: "OCR processing timed out. The document may be too large or complex.",
    
    ErrorCode.LLM_CONNECTION_ERROR: "Cannot connect to the LLM service. Please ensure Ollama or LMStudio is running.",
    ErrorCode.LLM_MODEL_NOT_FOUND: "The requested model is not available. Please check available models in Ollama/LMStudio.",
    ErrorCode.LLM_PROVIDER_ERROR: "The LLM provider returned an error. Please try again or switch to a different model.",
    ErrorCode.LLM_TIMEOUT: "LLM request timed out. Please try again with a shorter prompt.",
    
    ErrorCode.VALIDATION_ERROR: "The submitted data is invalid. Please check the form and correct any errors.",
    ErrorCode.INVALID_JSON: "The JSON data is malformed. Please check the format and try again.",
    ErrorCode.MISSING_REQUIRED_FIELD: "A required field is missing. Please fill in all required fields.",
    
    ErrorCode.NETWORK_ERROR: "A network error occurred. Please check your internet connection.",
    ErrorCode.TIMEOUT: "The request timed out. Please try again.",
    ErrorCode.CONNECTION_REFUSED: "Connection refused. Please check that the service is running.",
    
    ErrorCode.INTERNAL_ERROR: "An internal error occurred. Please try again or contact support.",
    ErrorCode.NOT_FOUND: "The requested resource was not found.",
    ErrorCode.RATE_LIMITED: "Too many requests. Please wait before trying again.",
}

# Retryable error codes
RETRYABLE_ERRORS = {
    ErrorCode.MANAGER_IO_CONNECTION_ERROR,
    ErrorCode.MANAGER_IO_RATE_LIMITED,
    ErrorCode.MANAGER_IO_SERVER_ERROR,
    ErrorCode.OCR_CONNECTION_ERROR,
    ErrorCode.OCR_TIMEOUT,
    ErrorCode.LLM_CONNECTION_ERROR,
    ErrorCode.LLM_TIMEOUT,
    ErrorCode.NETWORK_ERROR,
    ErrorCode.TIMEOUT,
    ErrorCode.CONNECTION_REFUSED,
    ErrorCode.INTERNAL_ERROR,
}


def create_error_response(
    error_code: ErrorCode,
    message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    retry_after: Optional[int] = None,
) -> ErrorResponse:
    """Create a standardized error response.
    
    Args:
        error_code: The error code
        message: Optional custom message (uses default if not provided)
        details: Optional additional details
        retry_after: Optional retry delay in seconds
        
    Returns:
        ErrorResponse with suggested action
    """
    suggested_action = SUGGESTED_ACTIONS.get(error_code)
    is_retryable = error_code in RETRYABLE_ERRORS
    
    return ErrorResponse(
        error=error_code.value,
        error_code=error_code.value,
        message=message or suggested_action or "An error occurred",
        details=details,
        retry_after=retry_after,
        suggested_action=suggested_action,
        is_retryable=is_retryable,
    )


class AppException(HTTPException):
    """Application exception with standardized error response.
    
    Use this exception to raise errors with consistent formatting
    and suggested actions.
    """
    
    def __init__(
        self,
        error_code: ErrorCode,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        retry_after: Optional[int] = None,
    ):
        self.error_code = error_code
        self.error_response = create_error_response(
            error_code=error_code,
            message=message,
            details=details,
            retry_after=retry_after,
        )
        
        super().__init__(
            status_code=status_code,
            detail=self.error_response.model_dump(),
        )


# Convenience exception classes
class AuthenticationError(AppException):
    """Authentication-related errors."""
    
    def __init__(
        self,
        error_code: ErrorCode = ErrorCode.AUTH_UNAUTHORIZED,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            error_code=error_code,
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=message,
            details=details,
        )


class NotFoundError(AppException):
    """Resource not found errors."""
    
    def __init__(
        self,
        error_code: ErrorCode = ErrorCode.NOT_FOUND,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            error_code=error_code,
            status_code=status.HTTP_404_NOT_FOUND,
            message=message,
            details=details,
        )


class ValidationError(AppException):
    """Validation errors."""
    
    def __init__(
        self,
        error_code: ErrorCode = ErrorCode.VALIDATION_ERROR,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            error_code=error_code,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=message,
            details=details,
        )


class ServiceUnavailableError(AppException):
    """Service unavailable errors (OCR, LLM, Manager.io)."""
    
    def __init__(
        self,
        error_code: ErrorCode,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        retry_after: Optional[int] = None,
    ):
        super().__init__(
            error_code=error_code,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=message,
            details=details,
            retry_after=retry_after,
        )


class RateLimitError(AppException):
    """Rate limit errors."""
    
    def __init__(
        self,
        error_code: ErrorCode = ErrorCode.RATE_LIMITED,
        message: Optional[str] = None,
        retry_after: int = 60,
    ):
        super().__init__(
            error_code=error_code,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            message=message,
            retry_after=retry_after,
        )
