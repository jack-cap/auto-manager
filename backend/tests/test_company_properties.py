"""Property-based tests for company configuration functionality.

Uses Hypothesis for property-based testing to validate universal correctness
properties across all valid inputs.

Feature: manager-io-bookkeeper
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from cryptography.fernet import Fernet
from hypothesis import given, settings as hyp_settings, strategies as st, assume

from app.services.encryption import EncryptionService
from app.services.company import CompanyConfigService
from app.models.company import CompanyConfig


# Custom strategies for generating test data

# Company name strategy - non-empty printable strings
company_name_strategy = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(
        min_codepoint=32,
        max_codepoint=126,
        blacklist_characters='\x00'
    )
).filter(lambda x: len(x.strip()) > 0)

# API key strategy - non-empty strings that could be valid API keys
api_key_strategy = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(
        min_codepoint=32,
        max_codepoint=126,
        blacklist_characters='\x00'
    )
).filter(lambda x: len(x.strip()) > 0)

# Base URL strategy - valid HTTP/HTTPS URLs
base_url_strategy = st.sampled_from([
    "http://localhost:8080/api2",
    "https://manager.example.com/api2",
    "https://accounting.company.io/api2",
    "http://192.168.1.100:5000/api2",
    "https://manager.internal.corp/api2",
]).flatmap(
    lambda base: st.just(base) | st.builds(
        lambda suffix: f"{base}/{suffix}",
        st.text(min_size=0, max_size=20, alphabet=st.characters(
            whitelist_categories=('L', 'N'),
        ))
    )
)

# User ID strategy - UUID strings
user_id_strategy = st.uuids().map(str)


class TestCompanyConfigRoundTripProperty:
    """Property 3: Company Configuration Round-Trip
    
    For any valid company configuration (name, API key, base URL), creating
    then retrieving the company SHALL return equivalent data (with API key
    decrypted), and updating then retrieving SHALL reflect the updates.
    
    **Validates: Requirements 2.1, 2.3**
    """
    
    @staticmethod
    async def _create_test_db():
        """Create a fresh in-memory database for each test iteration."""
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )
        from app.models.base import BaseModel
        
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        
        async with engine.begin() as conn:
            await conn.run_sync(BaseModel.metadata.create_all)
        
        async_session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        
        return engine, async_session_factory
    
    @given(
        user_id=user_id_strategy,
        name=company_name_strategy,
        api_key=api_key_strategy,
        base_url=base_url_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_create_then_get_returns_equivalent_data(
        self,
        user_id: str,
        name: str,
        api_key: str,
        base_url: str,
    ):
        """Feature: manager-io-bookkeeper, Property 3: Company Configuration Round-Trip
        
        Creating a company then retrieving it should return equivalent data.
        **Validates: Requirements 2.1**
        """
        async def run_test():
            engine, session_factory = await self._create_test_db()
            encryption_key = Fernet.generate_key().decode()
            encryption_service = EncryptionService(encryption_key)
            
            try:
                async with session_factory() as db_session:
                    service = CompanyConfigService(db_session, encryption_service)
                    
                    # Create company (skip connection validation for property test)
                    created = await service.create(
                        user_id=user_id,
                        name=name,
                        base_url=base_url,
                        api_key=api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Retrieve company
                    retrieved = await service.get_by_id(created.id, user_id)
                    
                    # Property: retrieved data should match created data
                    assert retrieved.id == created.id, "ID should match"
                    assert retrieved.user_id == user_id, "User ID should match"
                    assert retrieved.name == name, "Name should match"
                    
                    # Base URL should be normalized (trailing slash removed)
                    expected_base_url = base_url.rstrip("/")
                    assert retrieved.base_url == expected_base_url, "Base URL should match (normalized)"
                    
                    # Property: decrypted API key should match original
                    decrypted_api_key = service.decrypt_api_key(retrieved)
                    assert decrypted_api_key == api_key, "Decrypted API key should match original"
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        user_id=user_id_strategy,
        name=company_name_strategy,
        api_key=api_key_strategy,
        base_url=base_url_strategy,
        new_name=company_name_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_update_name_then_get_reflects_changes(
        self,
        user_id: str,
        name: str,
        api_key: str,
        base_url: str,
        new_name: str,
    ):
        """Feature: manager-io-bookkeeper, Property 3: Company Configuration Round-Trip
        
        Updating a company name then retrieving should reflect the update.
        **Validates: Requirements 2.3**
        """
        async def run_test():
            engine, session_factory = await self._create_test_db()
            encryption_key = Fernet.generate_key().decode()
            encryption_service = EncryptionService(encryption_key)
            
            try:
                async with session_factory() as db_session:
                    service = CompanyConfigService(db_session, encryption_service)
                    
                    # Create company
                    created = await service.create(
                        user_id=user_id,
                        name=name,
                        base_url=base_url,
                        api_key=api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Update name
                    await service.update(
                        company_id=created.id,
                        user_id=user_id,
                        name=new_name,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Retrieve and verify
                    retrieved = await service.get_by_id(created.id, user_id)
                    
                    # Property: name should be updated (service strips whitespace)
                    assert retrieved.name == new_name.strip(), "Name should be updated"
                    
                    # Property: other fields should remain unchanged
                    assert retrieved.base_url == base_url.rstrip("/"), "Base URL should remain unchanged"
                    decrypted_api_key = service.decrypt_api_key(retrieved)
                    assert decrypted_api_key == api_key, "API key should remain unchanged"
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        user_id=user_id_strategy,
        name=company_name_strategy,
        api_key=api_key_strategy,
        base_url=base_url_strategy,
        new_api_key=api_key_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_update_api_key_then_get_reflects_changes(
        self,
        user_id: str,
        name: str,
        api_key: str,
        base_url: str,
        new_api_key: str,
    ):
        """Feature: manager-io-bookkeeper, Property 3: Company Configuration Round-Trip
        
        Updating a company API key then retrieving should reflect the update.
        **Validates: Requirements 2.3**
        """
        async def run_test():
            engine, session_factory = await self._create_test_db()
            encryption_key = Fernet.generate_key().decode()
            encryption_service = EncryptionService(encryption_key)
            
            try:
                async with session_factory() as db_session:
                    service = CompanyConfigService(db_session, encryption_service)
                    
                    # Create company
                    created = await service.create(
                        user_id=user_id,
                        name=name,
                        base_url=base_url,
                        api_key=api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Update API key
                    await service.update(
                        company_id=created.id,
                        user_id=user_id,
                        api_key=new_api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Retrieve and verify
                    retrieved = await service.get_by_id(created.id, user_id)
                    
                    # Property: API key should be updated
                    decrypted_api_key = service.decrypt_api_key(retrieved)
                    assert decrypted_api_key == new_api_key, "API key should be updated"
                    
                    # Property: other fields should remain unchanged
                    assert retrieved.name == name, "Name should remain unchanged"
                    assert retrieved.base_url == base_url.rstrip("/"), "Base URL should remain unchanged"
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        user_id=user_id_strategy,
        name=company_name_strategy,
        api_key=api_key_strategy,
        base_url=base_url_strategy,
        new_base_url=base_url_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_update_base_url_then_get_reflects_changes(
        self,
        user_id: str,
        name: str,
        api_key: str,
        base_url: str,
        new_base_url: str,
    ):
        """Feature: manager-io-bookkeeper, Property 3: Company Configuration Round-Trip
        
        Updating a company base URL then retrieving should reflect the update.
        **Validates: Requirements 2.3**
        """
        async def run_test():
            engine, session_factory = await self._create_test_db()
            encryption_key = Fernet.generate_key().decode()
            encryption_service = EncryptionService(encryption_key)
            
            try:
                async with session_factory() as db_session:
                    service = CompanyConfigService(db_session, encryption_service)
                    
                    # Create company
                    created = await service.create(
                        user_id=user_id,
                        name=name,
                        base_url=base_url,
                        api_key=api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Update base URL
                    await service.update(
                        company_id=created.id,
                        user_id=user_id,
                        base_url=new_base_url,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Retrieve and verify
                    retrieved = await service.get_by_id(created.id, user_id)
                    
                    # Property: base URL should be updated (normalized)
                    assert retrieved.base_url == new_base_url.rstrip("/"), "Base URL should be updated"
                    
                    # Property: other fields should remain unchanged
                    assert retrieved.name == name, "Name should remain unchanged"
                    decrypted_api_key = service.decrypt_api_key(retrieved)
                    assert decrypted_api_key == api_key, "API key should remain unchanged"
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        user_id=user_id_strategy,
        name=company_name_strategy,
        api_key=api_key_strategy,
        base_url=base_url_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_get_all_for_user_returns_created_companies(
        self,
        user_id: str,
        name: str,
        api_key: str,
        base_url: str,
    ):
        """Feature: manager-io-bookkeeper, Property 3: Company Configuration Round-Trip
        
        Getting all companies for a user should include created companies.
        **Validates: Requirements 2.1**
        """
        async def run_test():
            engine, session_factory = await self._create_test_db()
            encryption_key = Fernet.generate_key().decode()
            encryption_service = EncryptionService(encryption_key)
            
            try:
                async with session_factory() as db_session:
                    service = CompanyConfigService(db_session, encryption_service)
                    
                    # Create company
                    created = await service.create(
                        user_id=user_id,
                        name=name,
                        base_url=base_url,
                        api_key=api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Get all companies for user
                    companies = await service.get_all_for_user(user_id)
                    
                    # Property: created company should be in the list
                    assert len(companies) >= 1, "Should have at least one company"
                    company_ids = [c.id for c in companies]
                    assert created.id in company_ids, "Created company should be in list"
                    
                    # Find the created company and verify data
                    found = next(c for c in companies if c.id == created.id)
                    assert found.name == name
                    assert found.base_url == base_url.rstrip("/")
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())


class TestAPIKeyEncryptionAtRestProperty:
    """Property 5: API Key Encryption at Rest
    
    For any stored company configuration, the api_key_encrypted field in the
    database SHALL NOT equal the plaintext API key, and decrypting it SHALL
    return the original API key.
    
    **Validates: Requirements 2.6**
    """
    
    @given(api_key=api_key_strategy)
    @hyp_settings(max_examples=20, deadline=None)
    def test_encrypted_api_key_not_equal_to_plaintext(self, api_key: str):
        """Feature: manager-io-bookkeeper, Property 5: API Key Encryption at Rest
        
        Encrypted API key should never equal the plaintext API key.
        **Validates: Requirements 2.6**
        """
        encryption_key = Fernet.generate_key().decode()
        encryption_service = EncryptionService(encryption_key)
        
        # Encrypt the API key
        encrypted = encryption_service.encrypt(api_key)
        
        # Property: encrypted != plaintext
        assert encrypted != api_key, "Encrypted API key should not equal plaintext"
    
    @given(api_key=api_key_strategy)
    @hyp_settings(max_examples=20, deadline=None)
    def test_decrypt_encrypted_returns_original(self, api_key: str):
        """Feature: manager-io-bookkeeper, Property 5: API Key Encryption at Rest
        
        Decrypting an encrypted API key should return the original plaintext.
        **Validates: Requirements 2.6**
        """
        encryption_key = Fernet.generate_key().decode()
        encryption_service = EncryptionService(encryption_key)
        
        # Encrypt then decrypt
        encrypted = encryption_service.encrypt(api_key)
        decrypted = encryption_service.decrypt(encrypted)
        
        # Property: decrypt(encrypt(x)) == x
        assert decrypted == api_key, "Decrypted API key should equal original"
    
    @given(api_key=api_key_strategy)
    @hyp_settings(max_examples=20, deadline=None)
    def test_same_api_key_produces_different_ciphertext(self, api_key: str):
        """Feature: manager-io-bookkeeper, Property 5: API Key Encryption at Rest
        
        Same API key encrypted twice should produce different ciphertext (due to IV).
        **Validates: Requirements 2.6**
        """
        encryption_key = Fernet.generate_key().decode()
        encryption_service = EncryptionService(encryption_key)
        
        # Encrypt the same API key twice
        encrypted1 = encryption_service.encrypt(api_key)
        encrypted2 = encryption_service.encrypt(api_key)
        
        # Property: same plaintext produces different ciphertext
        assert encrypted1 != encrypted2, "Same API key should produce different ciphertext"
        
        # But both should decrypt to the same value
        assert encryption_service.decrypt(encrypted1) == api_key
        assert encryption_service.decrypt(encrypted2) == api_key
    
    @staticmethod
    async def _create_test_db():
        """Create a fresh in-memory database for each test iteration."""
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )
        from app.models.base import BaseModel
        
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        
        async with engine.begin() as conn:
            await conn.run_sync(BaseModel.metadata.create_all)
        
        async_session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        
        return engine, async_session_factory
    
    @given(
        user_id=user_id_strategy,
        name=company_name_strategy,
        api_key=api_key_strategy,
        base_url=base_url_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_stored_api_key_encrypted_not_equal_plaintext(
        self,
        user_id: str,
        name: str,
        api_key: str,
        base_url: str,
    ):
        """Feature: manager-io-bookkeeper, Property 5: API Key Encryption at Rest
        
        The api_key_encrypted field in the database should not equal the plaintext.
        **Validates: Requirements 2.6**
        """
        async def run_test():
            engine, session_factory = await self._create_test_db()
            encryption_key = Fernet.generate_key().decode()
            encryption_service = EncryptionService(encryption_key)
            
            try:
                async with session_factory() as db_session:
                    service = CompanyConfigService(db_session, encryption_service)
                    
                    # Create company
                    created = await service.create(
                        user_id=user_id,
                        name=name,
                        base_url=base_url,
                        api_key=api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Property: stored encrypted value != plaintext
                    assert created.api_key_encrypted != api_key, \
                        "Stored api_key_encrypted should not equal plaintext API key"
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        user_id=user_id_strategy,
        name=company_name_strategy,
        api_key=api_key_strategy,
        base_url=base_url_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_stored_api_key_decrypts_to_original(
        self,
        user_id: str,
        name: str,
        api_key: str,
        base_url: str,
    ):
        """Feature: manager-io-bookkeeper, Property 5: API Key Encryption at Rest
        
        Decrypting the stored api_key_encrypted should return the original API key.
        **Validates: Requirements 2.6**
        """
        async def run_test():
            engine, session_factory = await self._create_test_db()
            encryption_key = Fernet.generate_key().decode()
            encryption_service = EncryptionService(encryption_key)
            
            try:
                async with session_factory() as db_session:
                    service = CompanyConfigService(db_session, encryption_service)
                    
                    # Create company
                    created = await service.create(
                        user_id=user_id,
                        name=name,
                        base_url=base_url,
                        api_key=api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Retrieve and decrypt
                    retrieved = await service.get_by_id(created.id, user_id)
                    decrypted = service.decrypt_api_key(retrieved)
                    
                    # Property: decrypted API key == original
                    assert decrypted == api_key, \
                        "Decrypted API key should equal original plaintext"
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        user_id=user_id_strategy,
        name=company_name_strategy,
        api_key=api_key_strategy,
        base_url=base_url_strategy,
        new_api_key=api_key_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_updated_api_key_encrypted_not_equal_plaintext(
        self,
        user_id: str,
        name: str,
        api_key: str,
        base_url: str,
        new_api_key: str,
    ):
        """Feature: manager-io-bookkeeper, Property 5: API Key Encryption at Rest
        
        After updating, the api_key_encrypted should not equal the new plaintext.
        **Validates: Requirements 2.6**
        """
        async def run_test():
            engine, session_factory = await self._create_test_db()
            encryption_key = Fernet.generate_key().decode()
            encryption_service = EncryptionService(encryption_key)
            
            try:
                async with session_factory() as db_session:
                    service = CompanyConfigService(db_session, encryption_service)
                    
                    # Create company
                    created = await service.create(
                        user_id=user_id,
                        name=name,
                        base_url=base_url,
                        api_key=api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Update API key
                    updated = await service.update(
                        company_id=created.id,
                        user_id=user_id,
                        api_key=new_api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Property: updated encrypted value != new plaintext
                    assert updated.api_key_encrypted != new_api_key, \
                        "Updated api_key_encrypted should not equal new plaintext"
                    
                    # Property: decrypted value == new plaintext
                    decrypted = service.decrypt_api_key(updated)
                    assert decrypted == new_api_key, \
                        "Decrypted API key should equal new plaintext"
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(api_key=api_key_strategy)
    @hyp_settings(max_examples=20, deadline=None)
    def test_encryption_with_wrong_key_fails_decryption(self, api_key: str):
        """Feature: manager-io-bookkeeper, Property 5: API Key Encryption at Rest
        
        Decrypting with a different key should fail.
        **Validates: Requirements 2.6**
        """
        from app.services.encryption import EncryptionError
        
        # Create two different encryption services with different keys
        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()
        
        service1 = EncryptionService(key1)
        service2 = EncryptionService(key2)
        
        # Encrypt with service1
        encrypted = service1.encrypt(api_key)
        
        # Property: decrypting with different key should fail
        with pytest.raises(EncryptionError):
            service2.decrypt(encrypted)


class TestUserDataIsolationProperty:
    """Property 4: User Data Isolation
    
    For any two distinct users with company configurations, querying companies
    for user A SHALL NOT return any companies belonging to user B.
    
    **Validates: Requirements 2.7**
    """
    
    @staticmethod
    async def _create_test_db():
        """Create a fresh in-memory database for each test iteration."""
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )
        from app.models.base import BaseModel
        
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        
        async with engine.begin() as conn:
            await conn.run_sync(BaseModel.metadata.create_all)
        
        async_session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        
        return engine, async_session_factory
    
    @given(
        user_a_id=user_id_strategy,
        user_b_id=user_id_strategy,
        user_a_company_name=company_name_strategy,
        user_b_company_name=company_name_strategy,
        user_a_api_key=api_key_strategy,
        user_b_api_key=api_key_strategy,
        user_a_base_url=base_url_strategy,
        user_b_base_url=base_url_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_get_all_for_user_does_not_return_other_users_companies(
        self,
        user_a_id: str,
        user_b_id: str,
        user_a_company_name: str,
        user_b_company_name: str,
        user_a_api_key: str,
        user_b_api_key: str,
        user_a_base_url: str,
        user_b_base_url: str,
    ):
        """Feature: manager-io-bookkeeper, Property 4: User Data Isolation
        
        Querying companies for user A should NOT return any companies belonging to user B.
        **Validates: Requirements 2.7**
        """
        # Ensure users are distinct
        assume(user_a_id != user_b_id)
        
        async def run_test():
            engine, session_factory = await self._create_test_db()
            encryption_key = Fernet.generate_key().decode()
            encryption_service = EncryptionService(encryption_key)
            
            try:
                async with session_factory() as db_session:
                    service = CompanyConfigService(db_session, encryption_service)
                    
                    # Create company for user A
                    company_a = await service.create(
                        user_id=user_a_id,
                        name=user_a_company_name,
                        base_url=user_a_base_url,
                        api_key=user_a_api_key,
                        validate_connection=False,
                    )
                    
                    # Create company for user B
                    company_b = await service.create(
                        user_id=user_b_id,
                        name=user_b_company_name,
                        base_url=user_b_base_url,
                        api_key=user_b_api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Get all companies for user A
                    user_a_companies = await service.get_all_for_user(user_a_id)
                    
                    # Property: user A's company list should NOT contain user B's company
                    user_a_company_ids = [c.id for c in user_a_companies]
                    assert company_b.id not in user_a_company_ids, \
                        "User A should not see user B's companies"
                    
                    # Property: user A's company list should contain user A's company
                    assert company_a.id in user_a_company_ids, \
                        "User A should see their own companies"
                    
                    # Get all companies for user B
                    user_b_companies = await service.get_all_for_user(user_b_id)
                    
                    # Property: user B's company list should NOT contain user A's company
                    user_b_company_ids = [c.id for c in user_b_companies]
                    assert company_a.id not in user_b_company_ids, \
                        "User B should not see user A's companies"
                    
                    # Property: user B's company list should contain user B's company
                    assert company_b.id in user_b_company_ids, \
                        "User B should see their own companies"
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        user_a_id=user_id_strategy,
        user_b_id=user_id_strategy,
        company_name=company_name_strategy,
        api_key=api_key_strategy,
        base_url=base_url_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_get_by_id_does_not_return_other_users_company(
        self,
        user_a_id: str,
        user_b_id: str,
        company_name: str,
        api_key: str,
        base_url: str,
    ):
        """Feature: manager-io-bookkeeper, Property 4: User Data Isolation
        
        User A cannot access user B's company via get_by_id.
        **Validates: Requirements 2.7**
        """
        from app.services.company import CompanyNotFoundError
        
        # Ensure users are distinct
        assume(user_a_id != user_b_id)
        
        async def run_test():
            engine, session_factory = await self._create_test_db()
            encryption_key = Fernet.generate_key().decode()
            encryption_service = EncryptionService(encryption_key)
            
            try:
                async with session_factory() as db_session:
                    service = CompanyConfigService(db_session, encryption_service)
                    
                    # Create company for user B
                    company_b = await service.create(
                        user_id=user_b_id,
                        name=company_name,
                        base_url=base_url,
                        api_key=api_key,
                        validate_connection=False,
                    )
                    await db_session.commit()
                    
                    # Property: user A should NOT be able to access user B's company
                    with pytest.raises(CompanyNotFoundError):
                        await service.get_by_id(company_b.id, user_a_id)
                    
                    # Property: user B should be able to access their own company
                    retrieved = await service.get_by_id(company_b.id, user_b_id)
                    assert retrieved.id == company_b.id, \
                        "User B should be able to access their own company"
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        user_a_id=user_id_strategy,
        user_b_id=user_id_strategy,
        num_companies_a=st.integers(min_value=1, max_value=5),
        num_companies_b=st.integers(min_value=1, max_value=5),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_multiple_companies_per_user_isolation(
        self,
        user_a_id: str,
        user_b_id: str,
        num_companies_a: int,
        num_companies_b: int,
    ):
        """Feature: manager-io-bookkeeper, Property 4: User Data Isolation
        
        With multiple companies per user, each user should only see their own companies.
        **Validates: Requirements 2.7**
        """
        # Ensure users are distinct
        assume(user_a_id != user_b_id)
        
        async def run_test():
            engine, session_factory = await self._create_test_db()
            encryption_key = Fernet.generate_key().decode()
            encryption_service = EncryptionService(encryption_key)
            
            try:
                async with session_factory() as db_session:
                    service = CompanyConfigService(db_session, encryption_service)
                    
                    # Create multiple companies for user A
                    user_a_company_ids = []
                    for i in range(num_companies_a):
                        company = await service.create(
                            user_id=user_a_id,
                            name=f"User A Company {i}",
                            base_url=f"http://localhost:{8000 + i}/api2",
                            api_key=f"api_key_a_{i}",
                            validate_connection=False,
                        )
                        user_a_company_ids.append(company.id)
                    
                    # Create multiple companies for user B
                    user_b_company_ids = []
                    for i in range(num_companies_b):
                        company = await service.create(
                            user_id=user_b_id,
                            name=f"User B Company {i}",
                            base_url=f"http://localhost:{9000 + i}/api2",
                            api_key=f"api_key_b_{i}",
                            validate_connection=False,
                        )
                        user_b_company_ids.append(company.id)
                    
                    await db_session.commit()
                    
                    # Get all companies for user A
                    user_a_companies = await service.get_all_for_user(user_a_id)
                    retrieved_a_ids = [c.id for c in user_a_companies]
                    
                    # Property: user A should see exactly their companies
                    assert len(user_a_companies) == num_companies_a, \
                        f"User A should have exactly {num_companies_a} companies"
                    
                    for company_id in user_a_company_ids:
                        assert company_id in retrieved_a_ids, \
                            "User A should see all their own companies"
                    
                    for company_id in user_b_company_ids:
                        assert company_id not in retrieved_a_ids, \
                            "User A should not see any of user B's companies"
                    
                    # Get all companies for user B
                    user_b_companies = await service.get_all_for_user(user_b_id)
                    retrieved_b_ids = [c.id for c in user_b_companies]
                    
                    # Property: user B should see exactly their companies
                    assert len(user_b_companies) == num_companies_b, \
                        f"User B should have exactly {num_companies_b} companies"
                    
                    for company_id in user_b_company_ids:
                        assert company_id in retrieved_b_ids, \
                            "User B should see all their own companies"
                    
                    for company_id in user_a_company_ids:
                        assert company_id not in retrieved_b_ids, \
                            "User B should not see any of user A's companies"
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
