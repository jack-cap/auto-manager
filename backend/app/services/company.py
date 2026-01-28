"""Company configuration service for managing Manager.io company configs."""

from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import CompanyConfig
from app.services.encryption import EncryptionService, EncryptionError


class CompanyConfigError(Exception):
    """Raised when company configuration operations fail."""
    pass


class CompanyNotFoundError(CompanyConfigError):
    """Raised when a company configuration is not found."""
    pass


class CompanyValidationError(CompanyConfigError):
    """Raised when company configuration validation fails."""
    pass


class ManagerIOConnectionError(CompanyConfigError):
    """Raised when Manager.io API connectivity validation fails."""
    pass


class CompanyConfigService:
    """Service for managing company configurations.
    
    Provides CRUD operations for company configurations with:
    - API key encryption/decryption using Fernet
    - Manager.io API connectivity validation
    - User isolation (users can only access their own companies)
    """
    
    def __init__(
        self,
        db: AsyncSession,
        encryption_service: Optional[EncryptionService] = None,
    ):
        """Initialize CompanyConfigService.
        
        Args:
            db: Async SQLAlchemy session
            encryption_service: Optional encryption service instance.
                              If not provided, creates a new one.
        """
        self.db = db
        self._encryption = encryption_service or EncryptionService()
    
    async def create(
        self,
        user_id: str,
        name: str,
        base_url: str,
        api_key: str,
        validate_connection: bool = True,
    ) -> CompanyConfig:
        """Create a new company configuration.
        
        Args:
            user_id: ID of the user creating the company
            name: Display name for the company
            base_url: Manager.io API base URL
            api_key: Manager.io API key (will be encrypted)
            validate_connection: Whether to validate Manager.io connectivity
            
        Returns:
            Created CompanyConfig instance
            
        Raises:
            CompanyValidationError: If validation fails
            ManagerIOConnectionError: If Manager.io connectivity check fails
            EncryptionError: If API key encryption fails
        """
        # Validate inputs
        self._validate_inputs(name, base_url, api_key)
        
        # Validate Manager.io connectivity if requested
        if validate_connection:
            await self._validate_manager_io_connection(base_url, api_key)
        
        # Encrypt API key
        try:
            api_key_encrypted = self._encryption.encrypt(api_key)
        except EncryptionError as e:
            raise CompanyConfigError(f"Failed to encrypt API key: {e}")
        
        # Create company config
        company = CompanyConfig(
            user_id=user_id,
            name=name,
            base_url=base_url.rstrip("/"),  # Normalize URL
            api_key_encrypted=api_key_encrypted,
        )
        
        self.db.add(company)
        await self.db.flush()
        await self.db.refresh(company)
        
        return company
    
    async def get_by_id(
        self,
        company_id: str,
        user_id: str,
    ) -> CompanyConfig:
        """Get a company configuration by ID.
        
        Args:
            company_id: ID of the company to retrieve
            user_id: ID of the user (for access control)
            
        Returns:
            CompanyConfig instance
            
        Raises:
            CompanyNotFoundError: If company not found or belongs to another user
        """
        result = await self.db.execute(
            select(CompanyConfig).where(
                CompanyConfig.id == company_id,
                CompanyConfig.user_id == user_id,
            )
        )
        company = result.scalar_one_or_none()
        
        if not company:
            raise CompanyNotFoundError(
                f"Company configuration not found: {company_id}"
            )
        
        return company
    
    async def get_all_for_user(self, user_id: str) -> list[CompanyConfig]:
        """Get all company configurations for a user.
        
        Args:
            user_id: ID of the user
            
        Returns:
            List of CompanyConfig instances
        """
        result = await self.db.execute(
            select(CompanyConfig)
            .where(CompanyConfig.user_id == user_id)
            .order_by(CompanyConfig.name)
        )
        return list(result.scalars().all())
    
    async def update(
        self,
        company_id: str,
        user_id: str,
        name: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        validate_connection: bool = True,
    ) -> CompanyConfig:
        """Update a company configuration.
        
        Args:
            company_id: ID of the company to update
            user_id: ID of the user (for access control)
            name: New display name (optional)
            base_url: New Manager.io API base URL (optional)
            api_key: New Manager.io API key (optional, will be encrypted)
            validate_connection: Whether to validate Manager.io connectivity
            
        Returns:
            Updated CompanyConfig instance
            
        Raises:
            CompanyNotFoundError: If company not found or belongs to another user
            CompanyValidationError: If validation fails
            ManagerIOConnectionError: If Manager.io connectivity check fails
        """
        company = await self.get_by_id(company_id, user_id)
        
        # Update fields if provided
        if name is not None:
            if not name.strip():
                raise CompanyValidationError("Company name cannot be empty")
            company.name = name.strip()
        
        if base_url is not None:
            if not base_url.strip():
                raise CompanyValidationError("Base URL cannot be empty")
            company.base_url = base_url.strip().rstrip("/")
        
        if api_key is not None:
            if not api_key.strip():
                raise CompanyValidationError("API key cannot be empty")
            try:
                company.api_key_encrypted = self._encryption.encrypt(api_key)
            except EncryptionError as e:
                raise CompanyConfigError(f"Failed to encrypt API key: {e}")
        
        # Validate Manager.io connectivity if URL or API key changed
        if validate_connection and (base_url is not None or api_key is not None):
            # Get the current API key for validation
            current_api_key = api_key if api_key is not None else self.decrypt_api_key(company)
            await self._validate_manager_io_connection(
                company.base_url,
                current_api_key,
            )
        
        await self.db.flush()
        await self.db.refresh(company)
        
        return company
    
    async def delete(self, company_id: str, user_id: str) -> None:
        """Delete a company configuration.
        
        Args:
            company_id: ID of the company to delete
            user_id: ID of the user (for access control)
            
        Raises:
            CompanyNotFoundError: If company not found or belongs to another user
        """
        company = await self.get_by_id(company_id, user_id)
        await self.db.delete(company)
        await self.db.flush()
    
    def decrypt_api_key(self, company: CompanyConfig) -> str:
        """Decrypt the API key for a company configuration.
        
        Args:
            company: CompanyConfig instance
            
        Returns:
            Decrypted API key
            
        Raises:
            EncryptionError: If decryption fails
        """
        return self._encryption.decrypt(company.api_key_encrypted)
    
    def _validate_inputs(self, name: str, base_url: str, api_key: str) -> None:
        """Validate company configuration inputs.
        
        Args:
            name: Company name
            base_url: Manager.io API base URL
            api_key: Manager.io API key
            
        Raises:
            CompanyValidationError: If validation fails
        """
        if not name or not name.strip():
            raise CompanyValidationError("Company name is required")
        
        if not base_url or not base_url.strip():
            raise CompanyValidationError("Base URL is required")
        
        if not api_key or not api_key.strip():
            raise CompanyValidationError("API key is required")
        
        # Validate URL format
        base_url = base_url.strip()
        if not base_url.startswith(("http://", "https://")):
            raise CompanyValidationError(
                "Base URL must start with http:// or https://"
            )
    
    async def _validate_manager_io_connection(
        self,
        base_url: str,
        api_key: str,
    ) -> None:
        """Validate Manager.io API connectivity.
        
        Makes a test request to the Manager.io API to verify credentials.
        
        Args:
            base_url: Manager.io API base URL
            api_key: Manager.io API key
            
        Raises:
            ManagerIOConnectionError: If connectivity check fails
        """
        # Normalize URL
        base_url = base_url.rstrip("/")
        
        # Try to fetch chart of accounts as a connectivity test
        # This is a lightweight endpoint that requires authentication
        test_url = f"{base_url}/chart-of-accounts"
        
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                response = await client.get(
                    test_url,
                    headers={"X-API-KEY": api_key},
                )
                
                if response.status_code == 401:
                    raise ManagerIOConnectionError(
                        "Invalid API key. Please check your Manager.io API credentials."
                    )
                elif response.status_code == 403:
                    raise ManagerIOConnectionError(
                        "Access forbidden. The API key may not have sufficient permissions."
                    )
                elif response.status_code >= 400:
                    raise ManagerIOConnectionError(
                        f"Manager.io API returned error: {response.status_code}"
                    )
                    
        except httpx.ConnectError:
            raise ManagerIOConnectionError(
                f"Cannot connect to Manager.io at {base_url}. "
                "Please verify the URL and ensure the server is running."
            )
        except httpx.TimeoutException:
            raise ManagerIOConnectionError(
                f"Connection to Manager.io at {base_url} timed out. "
                "Please verify the URL and network connectivity."
            )
        except ManagerIOConnectionError:
            raise
        except Exception as e:
            raise ManagerIOConnectionError(
                f"Failed to validate Manager.io connection: {e}"
            )
    
    async def check_connection(
        self,
        company_id: str,
        user_id: str,
    ) -> bool:
        """Check if a company's Manager.io connection is valid.
        
        Args:
            company_id: ID of the company to check
            user_id: ID of the user (for access control)
            
        Returns:
            True if connection is valid, False otherwise
        """
        try:
            company = await self.get_by_id(company_id, user_id)
            api_key = self.decrypt_api_key(company)
            await self._validate_manager_io_connection(company.base_url, api_key)
            return True
        except (CompanyNotFoundError, ManagerIOConnectionError, EncryptionError):
            return False
