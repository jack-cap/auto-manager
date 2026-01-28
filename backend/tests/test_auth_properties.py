"""Property-based tests for authentication functionality.

Uses Hypothesis for property-based testing to validate universal correctness
properties across all valid inputs.

Feature: manager-io-bookkeeper
"""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from hypothesis import given, settings as hyp_settings, strategies as st, assume
from jose import jwt

from app.core.config import settings as app_settings
from app.services.auth import AuthService


# Custom strategies for generating test data
# Use printable ASCII for passwords to avoid encoding issues with bcrypt
password_strategy = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(
        min_codepoint=32,
        max_codepoint=126,
        blacklist_characters='\x00'
    )
)

email_strategy = st.emails()

name_strategy = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=('L', 'N', 'Zs'))
).filter(lambda x: len(x.strip()) > 0)


class TestPasswordHashingProperty:
    """Property 1: Password Hashing Security
    
    For any plaintext password, after hashing with the AuthService, the stored
    hash SHALL NOT equal the plaintext password, and verifying the original
    password against the hash SHALL return true.
    
    **Validates: Requirements 1.7**
    
    Note: bcrypt is intentionally slow (~0.4s per hash), so we use fewer examples
    for tests involving hashing to keep test runtime reasonable.
    """
    
    @given(password=password_strategy)
    @hyp_settings(max_examples=20, deadline=None)
    def test_hash_never_equals_plaintext(self, password: str):
        """Feature: manager-io-bookkeeper, Property 1: Password Hashing Security
        
        Hash should never equal the plaintext password.
        **Validates: Requirements 1.7**
        """
        db = MagicMock()
        auth_service = AuthService(db)
        
        hashed = auth_service.hash_password(password)
        
        # Property: hash != plaintext
        assert hashed != password, "Hash should never equal plaintext password"
    
    @given(password=password_strategy)
    @hyp_settings(max_examples=20, deadline=None)
    def test_verify_returns_true_for_correct_password(self, password: str):
        """Feature: manager-io-bookkeeper, Property 1: Password Hashing Security
        
        Verifying the original password against its hash should return True.
        **Validates: Requirements 1.7**
        """
        db = MagicMock()
        auth_service = AuthService(db)
        
        hashed = auth_service.hash_password(password)
        
        # Property: verify(password, hash(password)) == True
        assert auth_service.verify_password(password, hashed) is True, \
            "Verification should return True for correct password"
    
    @given(password=password_strategy, wrong_password=password_strategy)
    @hyp_settings(max_examples=20, deadline=None)
    def test_verify_returns_false_for_wrong_password(self, password: str, wrong_password: str):
        """Feature: manager-io-bookkeeper, Property 1: Password Hashing Security
        
        Verifying a different password against a hash should return False.
        **Validates: Requirements 1.7**
        """
        # Skip if passwords happen to be the same
        assume(password != wrong_password)
        
        db = MagicMock()
        auth_service = AuthService(db)
        
        hashed = auth_service.hash_password(password)
        
        # Property: verify(wrong_password, hash(password)) == False
        assert auth_service.verify_password(wrong_password, hashed) is False, \
            "Verification should return False for wrong password"
    
    @given(password=password_strategy)
    @hyp_settings(max_examples=20, deadline=None)
    def test_hash_produces_valid_bcrypt_format(self, password: str):
        """Feature: manager-io-bookkeeper, Property 1: Password Hashing Security
        
        Hash should be a valid bcrypt hash format.
        **Validates: Requirements 1.7**
        """
        db = MagicMock()
        auth_service = AuthService(db)
        
        hashed = auth_service.hash_password(password)
        
        # Property: hash starts with bcrypt prefix
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$"), \
            "Hash should be valid bcrypt format"
    
    @given(password=password_strategy)
    @hyp_settings(max_examples=20, deadline=None)
    def test_same_password_produces_different_hashes(self, password: str):
        """Feature: manager-io-bookkeeper, Property 1: Password Hashing Security
        
        Same password should produce different hashes due to random salt.
        **Validates: Requirements 1.7**
        """
        db = MagicMock()
        auth_service = AuthService(db)
        
        hash1 = auth_service.hash_password(password)
        hash2 = auth_service.hash_password(password)
        
        # Property: hash(password) != hash(password) due to salt
        assert hash1 != hash2, "Same password should produce different hashes"
        
        # But both should verify correctly
        assert auth_service.verify_password(password, hash1) is True
        assert auth_service.verify_password(password, hash2) is True



class TestSessionTokenLifecycleProperty:
    """Property 2: Session Token Lifecycle
    
    For any valid user credentials, creating a session SHALL produce a token
    that validates successfully until expiration, and after logout or expiration,
    the same token SHALL fail validation.
    
    **Validates: Requirements 1.2, 1.5, 1.6, 1.8**
    """
    
    @given(user_id=st.uuids().map(str))
    @hyp_settings(max_examples=20, deadline=None)
    def test_access_token_validates_before_expiration(self, user_id: str):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Access token should validate successfully before expiration.
        **Validates: Requirements 1.2, 1.8**
        """
        db = MagicMock()
        auth_service = AuthService(db)
        
        # Create access token
        token = auth_service._create_access_token(user_id)
        
        # Decode and verify token is valid
        payload = jwt.decode(
            token,
            app_settings.secret_key,
            algorithms=[app_settings.jwt_algorithm],
        )
        
        # Property: token contains correct user_id and type
        assert payload["sub"] == user_id, "Token should contain correct user_id"
        assert payload["type"] == "access", "Token should be access type"
        assert "exp" in payload, "Token should have expiration"
        
        # Property: expiration is in the future
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert exp_time > datetime.now(timezone.utc), "Token should not be expired"
    
    @given(user_id=st.uuids().map(str))
    @hyp_settings(max_examples=20, deadline=None)
    def test_refresh_token_validates_before_expiration(self, user_id: str):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Refresh token should validate successfully before expiration.
        **Validates: Requirements 1.2, 1.8**
        """
        db = MagicMock()
        auth_service = AuthService(db)
        
        # Create refresh token
        token, expires_at = auth_service._create_refresh_token(user_id)
        
        # Decode and verify token is valid
        payload = jwt.decode(
            token,
            app_settings.secret_key,
            algorithms=[app_settings.jwt_algorithm],
        )
        
        # Property: token contains correct user_id and type
        assert payload["sub"] == user_id, "Token should contain correct user_id"
        assert payload["type"] == "refresh", "Token should be refresh type"
        assert "exp" in payload, "Token should have expiration"
        
        # Property: expiration is in the future
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert exp_time > datetime.now(timezone.utc), "Token should not be expired"
        
        # Property: returned expires_at matches token expiration
        assert abs((exp_time - expires_at).total_seconds()) < 2, \
            "Returned expires_at should match token expiration"
    
    @given(user_id=st.uuids().map(str))
    @hyp_settings(max_examples=20, deadline=None)
    def test_expired_access_token_fails_validation(self, user_id: str):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Expired access token should fail validation.
        **Validates: Requirements 1.6**
        """
        from jose import ExpiredSignatureError
        
        db = MagicMock()
        auth_service = AuthService(db)
        
        # Create already-expired token
        token = auth_service._create_access_token(
            user_id,
            expires_delta=timedelta(seconds=-10)  # Already expired
        )
        
        # Property: expired token should raise ExpiredSignatureError
        with pytest.raises(ExpiredSignatureError):
            jwt.decode(
                token,
                app_settings.secret_key,
                algorithms=[app_settings.jwt_algorithm],
            )
    
    @given(user_id=st.uuids().map(str))
    @hyp_settings(max_examples=20, deadline=None)
    def test_expired_refresh_token_fails_validation(self, user_id: str):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Expired refresh token should fail validation.
        **Validates: Requirements 1.6**
        """
        from jose import ExpiredSignatureError
        
        db = MagicMock()
        auth_service = AuthService(db)
        
        # Create already-expired token
        token, _ = auth_service._create_refresh_token(
            user_id,
            expires_delta=timedelta(seconds=-10)  # Already expired
        )
        
        # Property: expired token should raise ExpiredSignatureError
        with pytest.raises(ExpiredSignatureError):
            jwt.decode(
                token,
                app_settings.secret_key,
                algorithms=[app_settings.jwt_algorithm],
            )
    
    @given(user_id=st.uuids().map(str))
    @hyp_settings(max_examples=20, deadline=None)
    def test_access_token_rejected_as_refresh_token(self, user_id: str):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Access token should be rejected when used as refresh token.
        **Validates: Requirements 1.5**
        """
        db = MagicMock()
        auth_service = AuthService(db)
        
        # Create access token
        access_token = auth_service._create_access_token(user_id)
        
        # Decode token
        payload = jwt.decode(
            access_token,
            app_settings.secret_key,
            algorithms=[app_settings.jwt_algorithm],
        )
        
        # Property: access token has type "access", not "refresh"
        assert payload["type"] == "access", "Access token should have type 'access'"
        assert payload["type"] != "refresh", "Access token should not be usable as refresh"
    
    @given(user_id=st.uuids().map(str))
    @hyp_settings(max_examples=20, deadline=None)
    def test_refresh_token_rejected_as_access_token(self, user_id: str):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Refresh token should be rejected when used as access token.
        **Validates: Requirements 1.5**
        """
        db = MagicMock()
        auth_service = AuthService(db)
        
        # Create refresh token
        refresh_token, _ = auth_service._create_refresh_token(user_id)
        
        # Decode token
        payload = jwt.decode(
            refresh_token,
            app_settings.secret_key,
            algorithms=[app_settings.jwt_algorithm],
        )
        
        # Property: refresh token has type "refresh", not "access"
        assert payload["type"] == "refresh", "Refresh token should have type 'refresh'"
        assert payload["type"] != "access", "Refresh token should not be usable as access"
    
    @given(
        user_id=st.uuids().map(str),
        expire_minutes=st.integers(min_value=1, max_value=1440)
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_token_expiration_configurable(self, user_id: str, expire_minutes: int):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Token expiration should be configurable.
        **Validates: Requirements 1.8**
        """
        db = MagicMock()
        auth_service = AuthService(db)
        
        # Create token with custom expiration
        expires_delta = timedelta(minutes=expire_minutes)
        token = auth_service._create_access_token(user_id, expires_delta)
        
        # Decode token
        payload = jwt.decode(
            token,
            app_settings.secret_key,
            algorithms=[app_settings.jwt_algorithm],
        )
        
        # Property: expiration should be approximately expire_minutes from now
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        expected_exp = datetime.now(timezone.utc) + expires_delta
        
        # Allow 5 second tolerance
        assert abs((exp_time - expected_exp).total_seconds()) < 5, \
            f"Token expiration should be {expire_minutes} minutes from now"
    
    @given(user_id=st.uuids().map(str))
    @hyp_settings(max_examples=20, deadline=None)
    def test_different_users_get_different_tokens(self, user_id: str):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Different users should get different tokens.
        **Validates: Requirements 1.2**
        """
        import uuid
        
        db = MagicMock()
        auth_service = AuthService(db)
        
        # Create another user_id
        other_user_id = str(uuid.uuid4())
        assume(user_id != other_user_id)
        
        # Create tokens for both users
        token1 = auth_service._create_access_token(user_id)
        token2 = auth_service._create_access_token(other_user_id)
        
        # Property: tokens should be different
        assert token1 != token2, "Different users should get different tokens"
        
        # Decode and verify user_ids
        payload1 = jwt.decode(token1, app_settings.secret_key, algorithms=[app_settings.jwt_algorithm])
        payload2 = jwt.decode(token2, app_settings.secret_key, algorithms=[app_settings.jwt_algorithm])
        
        assert payload1["sub"] == user_id
        assert payload2["sub"] == other_user_id
    
    @given(user_id=st.uuids().map(str))
    @hyp_settings(max_examples=20, deadline=None)
    def test_token_invalidated_with_wrong_secret(self, user_id: str):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Token should fail validation when decoded with wrong secret key.
        This simulates the security property that tokens cannot be forged.
        **Validates: Requirements 1.5**
        """
        from jose import JWTError
        
        db = MagicMock()
        auth_service = AuthService(db)
        
        # Create valid token
        token = auth_service._create_access_token(user_id)
        
        # Property: token should fail validation with wrong secret
        wrong_secret = "wrong-secret-key-that-is-different"
        with pytest.raises(JWTError):
            jwt.decode(
                token,
                wrong_secret,
                algorithms=[app_settings.jwt_algorithm],
            )
    
    @given(user_id=st.uuids().map(str))
    @hyp_settings(max_examples=20, deadline=None)
    def test_tampered_token_fails_validation(self, user_id: str):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Tampered token should fail validation.
        **Validates: Requirements 1.5**
        """
        from jose import JWTError
        import base64
        
        db = MagicMock()
        auth_service = AuthService(db)
        
        # Create valid token
        token = auth_service._create_access_token(user_id)
        
        # Tamper with the token by modifying the payload to change the user_id
        parts = token.split('.')
        if len(parts) == 3:
            # Decode the payload, modify it, and re-encode
            # This creates a token with a valid format but invalid signature
            payload_b64 = parts[1]
            # Add padding if needed
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += '=' * padding
            
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            # Modify the payload by changing a byte
            modified_bytes = bytes([payload_bytes[0] ^ 0xFF]) + payload_bytes[1:]
            modified_b64 = base64.urlsafe_b64encode(modified_bytes).rstrip(b'=').decode()
            
            tampered_token = f"{parts[0]}.{modified_b64}.{parts[2]}"
            
            # Property: tampered token should fail validation
            with pytest.raises(JWTError):
                jwt.decode(
                    tampered_token,
                    app_settings.secret_key,
                    algorithms=[app_settings.jwt_algorithm],
                )


@pytest.mark.asyncio
class TestSessionTokenLifecycleIntegrationProperty:
    """Property 2: Session Token Lifecycle - Integration Tests
    
    Tests that require database interaction to verify the full session
    lifecycle including logout behavior.
    
    **Validates: Requirements 1.2, 1.5, 1.6, 1.8**
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
        email=email_strategy,
        password=password_strategy,
        name=name_strategy
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_login_creates_valid_session_tokens(
        self,
        email: str,
        password: str,
        name: str,
    ):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Login should create valid access and refresh tokens.
        **Validates: Requirements 1.2**
        """
        async def run_test():
            engine, session_factory = await self._create_test_db()
            try:
                async with session_factory() as db_session:
                    auth_service = AuthService(db_session)
                    
                    # Register user
                    user = await auth_service.register(email, password, name)
                    await db_session.commit()
                    
                    # Login
                    token_pair = await auth_service.login(email, password)
                    await db_session.commit()
                    
                    # Property: access token should be valid
                    access_payload = jwt.decode(
                        token_pair.access_token,
                        app_settings.secret_key,
                        algorithms=[app_settings.jwt_algorithm],
                    )
                    assert access_payload["sub"] == user.id
                    assert access_payload["type"] == "access"
                    
                    # Property: refresh token should be valid
                    refresh_payload = jwt.decode(
                        token_pair.refresh_token,
                        app_settings.secret_key,
                        algorithms=[app_settings.jwt_algorithm],
                    )
                    assert refresh_payload["sub"] == user.id
                    assert refresh_payload["type"] == "refresh"
                    
                    # Property: get_current_user should return the user
                    current_user = await auth_service.get_current_user(token_pair.access_token)
                    assert current_user.id == user.id
                    assert current_user.email == email
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        email=email_strategy,
        password=password_strategy,
        name=name_strategy
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_refresh_token_fails_after_logout(
        self,
        email: str,
        password: str,
        name: str,
    ):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        After logout, refresh token should fail validation because session is deleted.
        **Validates: Requirements 1.5**
        """
        from app.services.auth import AuthenticationError
        
        async def run_test():
            engine, session_factory = await self._create_test_db()
            try:
                async with session_factory() as db_session:
                    auth_service = AuthService(db_session)
                    
                    # Register and login
                    user = await auth_service.register(email, password, name)
                    await db_session.commit()
                    
                    token_pair = await auth_service.login(email, password)
                    await db_session.commit()
                    
                    # Verify refresh token works before logout
                    new_tokens = await auth_service.refresh_token(token_pair.refresh_token)
                    await db_session.commit()
                    assert new_tokens.access_token is not None
                    
                    # Logout - invalidates all sessions
                    await auth_service.logout(user.id)
                    await db_session.commit()
                    
                    # Property: refresh token should fail after logout
                    with pytest.raises(AuthenticationError) as exc_info:
                        await auth_service.refresh_token(new_tokens.refresh_token)
                    
                    assert "not found or expired" in str(exc_info.value).lower()
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        email=email_strategy,
        password=password_strategy,
        name=name_strategy
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_multiple_sessions_all_invalidated_on_logout(
        self,
        email: str,
        password: str,
        name: str,
    ):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Logout should invalidate all sessions for a user.
        **Validates: Requirements 1.5**
        """
        from app.services.auth import AuthenticationError
        
        async def run_test():
            engine, session_factory = await self._create_test_db()
            try:
                async with session_factory() as db_session:
                    auth_service = AuthService(db_session)
                    
                    # Register user
                    user = await auth_service.register(email, password, name)
                    await db_session.commit()
                    
                    # Create multiple sessions (login multiple times)
                    token_pair1 = await auth_service.login(email, password)
                    await db_session.commit()
                    token_pair2 = await auth_service.login(email, password)
                    await db_session.commit()
                    token_pair3 = await auth_service.login(email, password)
                    await db_session.commit()
                    
                    # Logout - should invalidate ALL sessions
                    await auth_service.logout(user.id)
                    await db_session.commit()
                    
                    # Property: all refresh tokens should fail after logout
                    for token_pair in [token_pair1, token_pair2, token_pair3]:
                        with pytest.raises(AuthenticationError):
                            await auth_service.refresh_token(token_pair.refresh_token)
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        email=email_strategy,
        password=password_strategy,
        name=name_strategy
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_expired_access_token_rejected_by_get_current_user(
        self,
        email: str,
        password: str,
        name: str,
    ):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        Expired access token should be rejected by get_current_user.
        **Validates: Requirements 1.6**
        """
        from app.services.auth import AuthenticationError
        
        async def run_test():
            engine, session_factory = await self._create_test_db()
            try:
                async with session_factory() as db_session:
                    auth_service = AuthService(db_session)
                    
                    # Register user
                    user = await auth_service.register(email, password, name)
                    await db_session.commit()
                    
                    # Create expired access token
                    expired_token = auth_service._create_access_token(
                        user.id,
                        expires_delta=timedelta(seconds=-10)  # Already expired
                    )
                    
                    # Property: get_current_user should reject expired token
                    with pytest.raises(AuthenticationError) as exc_info:
                        await auth_service.get_current_user(expired_token)
                    
                    assert "invalid" in str(exc_info.value).lower() or "expired" in str(exc_info.value).lower()
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
    
    @given(
        email=email_strategy,
        password=password_strategy,
        name=name_strategy
    )
    @hyp_settings(max_examples=10, deadline=None)  # Reduced iterations due to required delay
    def test_refresh_token_rotation_invalidates_old_token(
        self,
        email: str,
        password: str,
        name: str,
    ):
        """Feature: manager-io-bookkeeper, Property 2: Session Token Lifecycle
        
        After refreshing, the old refresh token should be invalidated.
        **Validates: Requirements 1.5, 1.8**
        
        Note: This test adds a small delay between token generation to ensure
        tokens have different expiration timestamps. Without this, tokens
        generated in the same second would be identical (same user_id + same exp).
        The number of iterations is reduced to keep test runtime reasonable.
        """
        from app.services.auth import AuthenticationError
        import time
        
        async def run_test():
            engine, session_factory = await self._create_test_db()
            try:
                async with session_factory() as db_session:
                    auth_service = AuthService(db_session)
                    
                    # Register and login
                    user = await auth_service.register(email, password, name)
                    await db_session.commit()
                    
                    original_tokens = await auth_service.login(email, password)
                    await db_session.commit()
                    
                    # Store the original refresh token for later verification
                    original_refresh = original_tokens.refresh_token
                    
                    # Add a small delay to ensure the new token has a different timestamp
                    # This is necessary because JWT tokens with same user_id and same
                    # expiration timestamp will be identical
                    time.sleep(1.1)
                    
                    # Refresh token - this should invalidate the old refresh token
                    new_tokens = await auth_service.refresh_token(original_refresh)
                    await db_session.commit()
                    
                    # Property: new tokens should be valid and different from original
                    assert new_tokens.access_token is not None
                    assert new_tokens.refresh_token is not None
                    
                    # With the delay, tokens should now be different
                    assert new_tokens.refresh_token != original_refresh, \
                        "New refresh token should be different from original"
                    
                    # Property: old refresh token should be invalidated
                    # This is the key property - the old session is deleted
                    with pytest.raises(AuthenticationError):
                        await auth_service.refresh_token(original_refresh)
            finally:
                await engine.dispose()
        
        asyncio.run(run_test())
