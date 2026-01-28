"""Unit tests for CompanyConfigService and EncryptionService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from cryptography.fernet import Fernet

from app.services.encryption import EncryptionService, EncryptionError
from app.services.company import (
    CompanyConfigService,
    CompanyConfigError,
    CompanyNotFoundError,
    CompanyValidationError,
    ManagerIOConnectionError,
)
from app.models.company import CompanyConfig


class TestEncryptionService:
    """Tests for EncryptionService."""
    
    @pytest.fixture
    def encryption_key(self) -> str:
        """Generate a valid Fernet encryption key."""
        return Fernet.generate_key().decode()
    
    @pytest.fixture
    def encryption_service(self, encryption_key: str) -> EncryptionService:
        """Create an EncryptionService with a valid key."""
        return EncryptionService(encryption_key)
    
    def test_encrypt_returns_different_value(self, encryption_service: EncryptionService):
        """Encrypted value should not equal plaintext."""
        plaintext = "my-secret-api-key"
        encrypted = encryption_service.encrypt(plaintext)
        
        assert encrypted != plaintext
        assert len(encrypted) > 0
    
    def test_encrypt_produces_base64_string(self, encryption_service: EncryptionService):
        """Encrypted value should be a valid base64 string."""
        plaintext = "test-api-key"
        encrypted = encryption_service.encrypt(plaintext)
        
        # Fernet tokens are URL-safe base64
        import base64
        try:
            base64.urlsafe_b64decode(encrypted)
        except Exception:
            pytest.fail("Encrypted value is not valid base64")
    
    def test_decrypt_returns_original(self, encryption_service: EncryptionService):
        """Decryption should return the original plaintext."""
        plaintext = "my-secret-api-key-12345"
        encrypted = encryption_service.encrypt(plaintext)
        decrypted = encryption_service.decrypt(encrypted)
        
        assert decrypted == plaintext
    
    def test_same_plaintext_different_ciphertext(self, encryption_service: EncryptionService):
        """Same plaintext should produce different ciphertext (due to IV)."""
        plaintext = "same-api-key"
        encrypted1 = encryption_service.encrypt(plaintext)
        encrypted2 = encryption_service.encrypt(plaintext)
        
        assert encrypted1 != encrypted2
        # But both should decrypt to the same value
        assert encryption_service.decrypt(encrypted1) == plaintext
        assert encryption_service.decrypt(encrypted2) == plaintext
    
    def test_decrypt_with_wrong_key_fails(self, encryption_key: str):
        """Decryption with wrong key should fail."""
        service1 = EncryptionService(encryption_key)
        service2 = EncryptionService(Fernet.generate_key().decode())
        
        plaintext = "secret-data"
        encrypted = service1.encrypt(plaintext)
        
        with pytest.raises(EncryptionError) as exc_info:
            service2.decrypt(encrypted)
        
        assert "Invalid token" in str(exc_info.value)
    
    def test_encrypt_empty_string_fails(self, encryption_service: EncryptionService):
        """Encrypting empty string should fail."""
        with pytest.raises(EncryptionError) as exc_info:
            encryption_service.encrypt("")
        
        assert "Cannot encrypt empty string" in str(exc_info.value)
    
    def test_decrypt_empty_string_fails(self, encryption_service: EncryptionService):
        """Decrypting empty string should fail."""
        with pytest.raises(EncryptionError) as exc_info:
            encryption_service.decrypt("")
        
        assert "Cannot decrypt empty string" in str(exc_info.value)
    
    def test_decrypt_invalid_ciphertext_fails(self, encryption_service: EncryptionService):
        """Decrypting invalid ciphertext should fail."""
        with pytest.raises(EncryptionError) as exc_info:
            encryption_service.decrypt("not-valid-ciphertext")
        
        assert "Invalid token" in str(exc_info.value)
    
    def test_invalid_key_raises_error(self):
        """Invalid encryption key should raise error."""
        with pytest.raises(EncryptionError) as exc_info:
            EncryptionService("invalid-key")
        
        assert "Invalid encryption key" in str(exc_info.value)
    
    def test_missing_key_raises_error(self):
        """Missing encryption key should raise error."""
        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.encryption_key = ""
            
            with pytest.raises(EncryptionError) as exc_info:
                EncryptionService()
            
            assert "Encryption key not configured" in str(exc_info.value)
    
    def test_long_plaintext_encryption(self, encryption_service: EncryptionService):
        """Long plaintext should encrypt and decrypt correctly."""
        plaintext = "a" * 10000  # 10KB of data
        encrypted = encryption_service.encrypt(plaintext)
        decrypted = encryption_service.decrypt(encrypted)
        
        assert decrypted == plaintext
    
    def test_unicode_plaintext_encryption(self, encryption_service: EncryptionService):
        """Unicode plaintext should encrypt and decrypt correctly."""
        plaintext = "日本語テスト🔐🔑"
        encrypted = encryption_service.encrypt(plaintext)
        decrypted = encryption_service.decrypt(encrypted)
        
        assert decrypted == plaintext


class TestCompanyConfigServiceValidation:
    """Tests for CompanyConfigService input validation."""
    
    @pytest.fixture
    def encryption_key(self) -> str:
        """Generate a valid Fernet encryption key."""
        return Fernet.generate_key().decode()
    
    @pytest.fixture
    def encryption_service(self, encryption_key: str) -> EncryptionService:
        """Create an EncryptionService with a valid key."""
        return EncryptionService(encryption_key)
    
    @pytest.fixture
    def company_service(self, encryption_service: EncryptionService) -> CompanyConfigService:
        """Create a CompanyConfigService with mocked database."""
        db = AsyncMock()
        return CompanyConfigService(db, encryption_service)
    
    def test_validate_inputs_empty_name(self, company_service: CompanyConfigService):
        """Empty name should fail validation."""
        with pytest.raises(CompanyValidationError) as exc_info:
            company_service._validate_inputs("", "http://example.com", "api-key")
        
        assert "name is required" in str(exc_info.value)
    
    def test_validate_inputs_empty_base_url(self, company_service: CompanyConfigService):
        """Empty base URL should fail validation."""
        with pytest.raises(CompanyValidationError) as exc_info:
            company_service._validate_inputs("Company", "", "api-key")
        
        assert "Base URL is required" in str(exc_info.value)
    
    def test_validate_inputs_empty_api_key(self, company_service: CompanyConfigService):
        """Empty API key should fail validation."""
        with pytest.raises(CompanyValidationError) as exc_info:
            company_service._validate_inputs("Company", "http://example.com", "")
        
        assert "API key is required" in str(exc_info.value)
    
    def test_validate_inputs_invalid_url_scheme(self, company_service: CompanyConfigService):
        """URL without http/https should fail validation."""
        with pytest.raises(CompanyValidationError) as exc_info:
            company_service._validate_inputs("Company", "ftp://example.com", "api-key")
        
        assert "must start with http://" in str(exc_info.value)
    
    def test_validate_inputs_valid(self, company_service: CompanyConfigService):
        """Valid inputs should pass validation."""
        # Should not raise
        company_service._validate_inputs(
            "My Company",
            "https://manager.example.com/api2",
            "secret-api-key",
        )


class TestCompanyConfigServiceCreate:
    """Tests for CompanyConfigService.create()."""
    
    @pytest.fixture
    def encryption_key(self) -> str:
        """Generate a valid Fernet encryption key."""
        return Fernet.generate_key().decode()
    
    @pytest.fixture
    def encryption_service(self, encryption_key: str) -> EncryptionService:
        """Create an EncryptionService with a valid key."""
        return EncryptionService(encryption_key)
    
    @pytest.mark.asyncio
    async def test_create_success_without_validation(self, encryption_service: EncryptionService):
        """Create should succeed without connection validation."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        company = await service.create(
            user_id="user-123",
            name="Test Company",
            base_url="https://manager.example.com/api2",
            api_key="secret-api-key",
            validate_connection=False,
        )
        
        assert company.user_id == "user-123"
        assert company.name == "Test Company"
        assert company.base_url == "https://manager.example.com/api2"
        assert company.api_key_encrypted != "secret-api-key"
        
        # Verify API key can be decrypted
        decrypted = encryption_service.decrypt(company.api_key_encrypted)
        assert decrypted == "secret-api-key"
        
        db.add.assert_called_once()
        db.flush.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_normalizes_url(self, encryption_service: EncryptionService):
        """Create should normalize URL by removing trailing slash."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        company = await service.create(
            user_id="user-123",
            name="Test Company",
            base_url="https://manager.example.com/api2/",
            api_key="secret-api-key",
            validate_connection=False,
        )
        
        assert company.base_url == "https://manager.example.com/api2"
    
    @pytest.mark.asyncio
    async def test_create_with_connection_validation_success(self, encryption_service: EncryptionService):
        """Create should succeed when connection validation passes."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        with patch.object(service, "_validate_manager_io_connection") as mock_validate:
            mock_validate.return_value = None
            
            company = await service.create(
                user_id="user-123",
                name="Test Company",
                base_url="https://manager.example.com/api2",
                api_key="secret-api-key",
                validate_connection=True,
            )
            
            mock_validate.assert_called_once_with(
                "https://manager.example.com/api2",
                "secret-api-key",
            )
            assert company.name == "Test Company"
    
    @pytest.mark.asyncio
    async def test_create_with_connection_validation_failure(self, encryption_service: EncryptionService):
        """Create should fail when connection validation fails."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        with patch.object(service, "_validate_manager_io_connection") as mock_validate:
            mock_validate.side_effect = ManagerIOConnectionError("Connection failed")
            
            with pytest.raises(ManagerIOConnectionError) as exc_info:
                await service.create(
                    user_id="user-123",
                    name="Test Company",
                    base_url="https://manager.example.com/api2",
                    api_key="secret-api-key",
                    validate_connection=True,
                )
            
            assert "Connection failed" in str(exc_info.value)


class TestCompanyConfigServiceGet:
    """Tests for CompanyConfigService.get_by_id() and get_all_for_user()."""
    
    @pytest.fixture
    def encryption_key(self) -> str:
        """Generate a valid Fernet encryption key."""
        return Fernet.generate_key().decode()
    
    @pytest.fixture
    def encryption_service(self, encryption_key: str) -> EncryptionService:
        """Create an EncryptionService with a valid key."""
        return EncryptionService(encryption_key)
    
    @pytest.mark.asyncio
    async def test_get_by_id_success(self, encryption_service: EncryptionService):
        """get_by_id should return company for valid ID and user."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        mock_company = MagicMock(spec=CompanyConfig)
        mock_company.id = "company-123"
        mock_company.user_id = "user-123"
        mock_company.name = "Test Company"
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_company
        db.execute.return_value = mock_result
        
        company = await service.get_by_id("company-123", "user-123")
        
        assert company.id == "company-123"
        assert company.name == "Test Company"
    
    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, encryption_service: EncryptionService):
        """get_by_id should raise error when company not found."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result
        
        with pytest.raises(CompanyNotFoundError) as exc_info:
            await service.get_by_id("nonexistent", "user-123")
        
        assert "not found" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_all_for_user(self, encryption_service: EncryptionService):
        """get_all_for_user should return all companies for user."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        mock_company1 = MagicMock(spec=CompanyConfig)
        mock_company1.id = "company-1"
        mock_company1.name = "Company A"
        
        mock_company2 = MagicMock(spec=CompanyConfig)
        mock_company2.id = "company-2"
        mock_company2.name = "Company B"
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_company1, mock_company2]
        db.execute.return_value = mock_result
        
        companies = await service.get_all_for_user("user-123")
        
        assert len(companies) == 2
        assert companies[0].name == "Company A"
        assert companies[1].name == "Company B"
    
    @pytest.mark.asyncio
    async def test_get_all_for_user_empty(self, encryption_service: EncryptionService):
        """get_all_for_user should return empty list when no companies."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result
        
        companies = await service.get_all_for_user("user-123")
        
        assert len(companies) == 0


class TestCompanyConfigServiceUpdate:
    """Tests for CompanyConfigService.update()."""
    
    @pytest.fixture
    def encryption_key(self) -> str:
        """Generate a valid Fernet encryption key."""
        return Fernet.generate_key().decode()
    
    @pytest.fixture
    def encryption_service(self, encryption_key: str) -> EncryptionService:
        """Create an EncryptionService with a valid key."""
        return EncryptionService(encryption_key)
    
    @pytest.mark.asyncio
    async def test_update_name_only(self, encryption_service: EncryptionService):
        """Update should update only the name when specified."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        mock_company = MagicMock(spec=CompanyConfig)
        mock_company.id = "company-123"
        mock_company.user_id = "user-123"
        mock_company.name = "Old Name"
        mock_company.base_url = "https://example.com"
        mock_company.api_key_encrypted = encryption_service.encrypt("old-key")
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_company
        db.execute.return_value = mock_result
        
        company = await service.update(
            company_id="company-123",
            user_id="user-123",
            name="New Name",
            validate_connection=False,
        )
        
        assert company.name == "New Name"
    
    @pytest.mark.asyncio
    async def test_update_api_key(self, encryption_service: EncryptionService):
        """Update should encrypt new API key."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        old_encrypted = encryption_service.encrypt("old-key")
        
        mock_company = MagicMock(spec=CompanyConfig)
        mock_company.id = "company-123"
        mock_company.user_id = "user-123"
        mock_company.name = "Company"
        mock_company.base_url = "https://example.com"
        mock_company.api_key_encrypted = old_encrypted
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_company
        db.execute.return_value = mock_result
        
        await service.update(
            company_id="company-123",
            user_id="user-123",
            api_key="new-api-key",
            validate_connection=False,
        )
        
        # Verify new API key was encrypted
        new_encrypted = mock_company.api_key_encrypted
        assert new_encrypted != old_encrypted
        assert encryption_service.decrypt(new_encrypted) == "new-api-key"
    
    @pytest.mark.asyncio
    async def test_update_not_found(self, encryption_service: EncryptionService):
        """Update should raise error when company not found."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result
        
        with pytest.raises(CompanyNotFoundError):
            await service.update(
                company_id="nonexistent",
                user_id="user-123",
                name="New Name",
            )


class TestCompanyConfigServiceDelete:
    """Tests for CompanyConfigService.delete()."""
    
    @pytest.fixture
    def encryption_key(self) -> str:
        """Generate a valid Fernet encryption key."""
        return Fernet.generate_key().decode()
    
    @pytest.fixture
    def encryption_service(self, encryption_key: str) -> EncryptionService:
        """Create an EncryptionService with a valid key."""
        return EncryptionService(encryption_key)
    
    @pytest.mark.asyncio
    async def test_delete_success(self, encryption_service: EncryptionService):
        """Delete should remove company configuration."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        mock_company = MagicMock(spec=CompanyConfig)
        mock_company.id = "company-123"
        mock_company.user_id = "user-123"
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_company
        db.execute.return_value = mock_result
        
        await service.delete("company-123", "user-123")
        
        db.delete.assert_called_once_with(mock_company)
        db.flush.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_delete_not_found(self, encryption_service: EncryptionService):
        """Delete should raise error when company not found."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result
        
        with pytest.raises(CompanyNotFoundError):
            await service.delete("nonexistent", "user-123")


class TestCompanyConfigServiceDecrypt:
    """Tests for CompanyConfigService.decrypt_api_key()."""
    
    @pytest.fixture
    def encryption_key(self) -> str:
        """Generate a valid Fernet encryption key."""
        return Fernet.generate_key().decode()
    
    @pytest.fixture
    def encryption_service(self, encryption_key: str) -> EncryptionService:
        """Create an EncryptionService with a valid key."""
        return EncryptionService(encryption_key)
    
    def test_decrypt_api_key(self, encryption_service: EncryptionService):
        """decrypt_api_key should return original API key."""
        db = MagicMock()
        service = CompanyConfigService(db, encryption_service)
        
        original_key = "my-secret-api-key"
        encrypted = encryption_service.encrypt(original_key)
        
        mock_company = MagicMock(spec=CompanyConfig)
        mock_company.api_key_encrypted = encrypted
        
        decrypted = service.decrypt_api_key(mock_company)
        
        assert decrypted == original_key


class TestManagerIOConnectionValidation:
    """Tests for Manager.io connection validation."""
    
    @pytest.fixture
    def encryption_key(self) -> str:
        """Generate a valid Fernet encryption key."""
        return Fernet.generate_key().decode()
    
    @pytest.fixture
    def encryption_service(self, encryption_key: str) -> EncryptionService:
        """Create an EncryptionService with a valid key."""
        return EncryptionService(encryption_key)
    
    @pytest.mark.asyncio
    async def test_validate_connection_success(self, encryption_service: EncryptionService):
        """Validation should pass for successful API response."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        with patch("app.services.company.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.get.return_value = mock_response
            
            # Should not raise
            await service._validate_manager_io_connection(
                "https://manager.example.com/api2",
                "valid-api-key",
            )
            
            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            assert "chart-of-accounts" in call_args[0][0]
            assert call_args[1]["headers"]["X-API-KEY"] == "valid-api-key"
    
    @pytest.mark.asyncio
    async def test_validate_connection_invalid_api_key(self, encryption_service: EncryptionService):
        """Validation should fail for 401 response."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        with patch("app.services.company.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_client.get.return_value = mock_response
            
            with pytest.raises(ManagerIOConnectionError) as exc_info:
                await service._validate_manager_io_connection(
                    "https://manager.example.com/api2",
                    "invalid-api-key",
                )
            
            assert "Invalid API key" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_validate_connection_forbidden(self, encryption_service: EncryptionService):
        """Validation should fail for 403 response."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        with patch("app.services.company.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_client.get.return_value = mock_response
            
            with pytest.raises(ManagerIOConnectionError) as exc_info:
                await service._validate_manager_io_connection(
                    "https://manager.example.com/api2",
                    "api-key",
                )
            
            assert "Access forbidden" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_validate_connection_connect_error(self, encryption_service: EncryptionService):
        """Validation should fail for connection errors."""
        import httpx
        
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        with patch("app.services.company.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            
            with pytest.raises(ManagerIOConnectionError) as exc_info:
                await service._validate_manager_io_connection(
                    "https://manager.example.com/api2",
                    "api-key",
                )
            
            assert "Cannot connect" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_validate_connection_timeout(self, encryption_service: EncryptionService):
        """Validation should fail for timeout errors."""
        import httpx
        
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        with patch("app.services.company.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.TimeoutException("Timeout")
            
            with pytest.raises(ManagerIOConnectionError) as exc_info:
                await service._validate_manager_io_connection(
                    "https://manager.example.com/api2",
                    "api-key",
                )
            
            assert "timed out" in str(exc_info.value)


class TestCompanyConfigServiceCheckConnection:
    """Tests for CompanyConfigService.check_connection()."""
    
    @pytest.fixture
    def encryption_key(self) -> str:
        """Generate a valid Fernet encryption key."""
        return Fernet.generate_key().decode()
    
    @pytest.fixture
    def encryption_service(self, encryption_key: str) -> EncryptionService:
        """Create an EncryptionService with a valid key."""
        return EncryptionService(encryption_key)
    
    @pytest.mark.asyncio
    async def test_check_connection_success(self, encryption_service: EncryptionService):
        """check_connection should return True for valid connection."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        mock_company = MagicMock(spec=CompanyConfig)
        mock_company.id = "company-123"
        mock_company.user_id = "user-123"
        mock_company.base_url = "https://example.com"
        mock_company.api_key_encrypted = encryption_service.encrypt("api-key")
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_company
        db.execute.return_value = mock_result
        
        with patch.object(service, "_validate_manager_io_connection") as mock_validate:
            mock_validate.return_value = None
            
            result = await service.check_connection("company-123", "user-123")
            
            assert result is True
    
    @pytest.mark.asyncio
    async def test_check_connection_failure(self, encryption_service: EncryptionService):
        """check_connection should return False for invalid connection."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        mock_company = MagicMock(spec=CompanyConfig)
        mock_company.id = "company-123"
        mock_company.user_id = "user-123"
        mock_company.base_url = "https://example.com"
        mock_company.api_key_encrypted = encryption_service.encrypt("api-key")
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_company
        db.execute.return_value = mock_result
        
        with patch.object(service, "_validate_manager_io_connection") as mock_validate:
            mock_validate.side_effect = ManagerIOConnectionError("Failed")
            
            result = await service.check_connection("company-123", "user-123")
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_check_connection_not_found(self, encryption_service: EncryptionService):
        """check_connection should return False when company not found."""
        db = AsyncMock()
        service = CompanyConfigService(db, encryption_service)
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result
        
        result = await service.check_connection("nonexistent", "user-123")
        
        assert result is False
