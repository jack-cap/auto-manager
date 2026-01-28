"""Unit tests for AuthService."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from jose import jwt

from app.core.config import settings
from app.services.auth import AuthService, AuthenticationError, TokenPair


class TestPasswordHashing:
    """Tests for password hashing functionality."""
    
    def test_hash_password_returns_different_value(self):
        """Hash should not equal plaintext password."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        password = "mysecretpassword123"
        hashed = auth_service.hash_password(password)
        
        assert hashed != password
        assert len(hashed) > 0
    
    def test_hash_password_produces_bcrypt_hash(self):
        """Hash should be a valid bcrypt hash."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        password = "testpassword"
        hashed = auth_service.hash_password(password)
        
        # Bcrypt hashes start with $2b$ or $2a$
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    
    def test_verify_password_correct(self):
        """Verify should return True for correct password."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        password = "correctpassword"
        hashed = auth_service.hash_password(password)
        
        assert auth_service.verify_password(password, hashed) is True
    
    def test_verify_password_incorrect(self):
        """Verify should return False for incorrect password."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        password = "correctpassword"
        hashed = auth_service.hash_password(password)
        
        assert auth_service.verify_password("wrongpassword", hashed) is False
    
    def test_same_password_different_hashes(self):
        """Same password should produce different hashes (due to salt)."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        password = "samepassword"
        hash1 = auth_service.hash_password(password)
        hash2 = auth_service.hash_password(password)
        
        assert hash1 != hash2
        # But both should verify correctly
        assert auth_service.verify_password(password, hash1) is True
        assert auth_service.verify_password(password, hash2) is True


class TestTokenHashing:
    """Tests for token hashing functionality (SHA-256).
    
    Unlike bcrypt, SHA-256 handles arbitrary length inputs without truncation.
    This is critical for JWT tokens which exceed bcrypt's 72-byte limit.
    """
    
    def test_hash_token_returns_hex_string(self):
        """Token hash should be a 64-character hex string (SHA-256)."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        token = "some-jwt-token-here"
        hashed = auth_service._hash_token(token)
        
        assert len(hashed) == 64  # SHA-256 produces 64 hex characters
        assert all(c in '0123456789abcdef' for c in hashed)
    
    def test_hash_token_deterministic(self):
        """Same token should always produce same hash (no salt)."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        token = "test-token"
        hash1 = auth_service._hash_token(token)
        hash2 = auth_service._hash_token(token)
        
        assert hash1 == hash2
    
    def test_verify_token_hash_correct(self):
        """Verify should return True for correct token."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        token = "my-refresh-token"
        hashed = auth_service._hash_token(token)
        
        assert auth_service._verify_token_hash(token, hashed) is True
    
    def test_verify_token_hash_incorrect(self):
        """Verify should return False for wrong token."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        token = "correct-token"
        hashed = auth_service._hash_token(token)
        
        assert auth_service._verify_token_hash("wrong-token", hashed) is False
    
    def test_long_tokens_produce_different_hashes(self):
        """Long tokens that differ only at the end should produce different hashes.
        
        This verifies we don't have the bcrypt 72-byte truncation issue.
        """
        db = MagicMock()
        auth_service = AuthService(db)
        
        # Create two tokens that share the same first 72 bytes but differ after
        base = "a" * 100  # 100 characters
        token1 = base + "1"
        token2 = base + "2"
        
        hash1 = auth_service._hash_token(token1)
        hash2 = auth_service._hash_token(token2)
        
        assert hash1 != hash2
        assert auth_service._verify_token_hash(token1, hash1) is True
        assert auth_service._verify_token_hash(token2, hash2) is True
        assert auth_service._verify_token_hash(token1, hash2) is False
        assert auth_service._verify_token_hash(token2, hash1) is False


class TestTokenGeneration:
    """Tests for JWT token generation."""
    
    def test_create_access_token(self):
        """Access token should be valid JWT with correct claims."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        user_id = "test-user-id-123"
        token = auth_service._create_access_token(user_id)
        
        # Decode and verify
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        
        assert payload["sub"] == user_id
        assert payload["type"] == "access"
        assert "exp" in payload
    
    def test_create_access_token_custom_expiry(self):
        """Access token should respect custom expiry."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        user_id = "test-user-id"
        expires_delta = timedelta(hours=2)
        token = auth_service._create_access_token(user_id, expires_delta)
        
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        
        # Expiry should be approximately 2 hours from now
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        expected_exp = datetime.now(timezone.utc) + expires_delta
        
        # Allow 5 second tolerance
        assert abs((exp_time - expected_exp).total_seconds()) < 5
    
    def test_create_refresh_token(self):
        """Refresh token should be valid JWT with correct claims."""
        db = MagicMock()
        auth_service = AuthService(db)
        
        user_id = "test-user-id-456"
        token, expires_at = auth_service._create_refresh_token(user_id)
        
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        
        assert payload["sub"] == user_id
        assert payload["type"] == "refresh"
        assert "exp" in payload
        assert isinstance(expires_at, datetime)


class TestRegister:
    """Tests for user registration."""
    
    @pytest.mark.asyncio
    async def test_register_success(self):
        """Registration should create user with hashed password."""
        # Mock database session
        db = AsyncMock()
        
        # Mock execute to return no existing user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result
        
        auth_service = AuthService(db)
        
        user = await auth_service.register(
            email="test@example.com",
            password="password123",
            name="Test User",
        )
        
        assert user.email == "test@example.com"
        assert user.name == "Test User"
        assert user.password_hash != "password123"
        assert user.password_hash.startswith("$2b$")
        
        # Verify db.add was called
        db.add.assert_called_once()
        db.flush.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_register_duplicate_email(self):
        """Registration should fail for duplicate email."""
        db = AsyncMock()
        
        # Mock execute to return existing user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()  # Existing user
        db.execute.return_value = mock_result
        
        auth_service = AuthService(db)
        
        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.register(
                email="existing@example.com",
                password="password123",
                name="Test User",
            )
        
        assert "already registered" in str(exc_info.value)


class TestLogin:
    """Tests for user login."""
    
    @pytest.mark.asyncio
    async def test_login_success(self):
        """Login should return tokens for valid credentials."""
        db = AsyncMock()
        auth_service = AuthService(db)
        
        # Create a mock user with hashed password
        password = "correctpassword"
        hashed = auth_service.hash_password(password)
        
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"
        mock_user.password_hash = hashed
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        db.execute.return_value = mock_result
        
        token_pair = await auth_service.login(
            email="test@example.com",
            password=password,
        )
        
        assert isinstance(token_pair, TokenPair)
        assert token_pair.access_token is not None
        assert token_pair.refresh_token is not None
        assert token_pair.token_type == "bearer"
        assert token_pair.expires_in > 0
        
        # Verify session was created
        db.add.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_login_invalid_email(self):
        """Login should fail for non-existent email."""
        db = AsyncMock()
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result
        
        auth_service = AuthService(db)
        
        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.login(
                email="nonexistent@example.com",
                password="anypassword",
            )
        
        assert "Invalid email or password" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_login_invalid_password(self):
        """Login should fail for wrong password."""
        db = AsyncMock()
        auth_service = AuthService(db)
        
        # Create mock user with different password
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.password_hash = auth_service.hash_password("correctpassword")
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        db.execute.return_value = mock_result
        
        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.login(
                email="test@example.com",
                password="wrongpassword",
            )
        
        assert "Invalid email or password" in str(exc_info.value)


class TestGetCurrentUser:
    """Tests for getting current user from token."""
    
    @pytest.mark.asyncio
    async def test_get_current_user_valid_token(self):
        """Should return user for valid access token."""
        db = AsyncMock()
        auth_service = AuthService(db)
        
        user_id = "user-456"
        token = auth_service._create_access_token(user_id)
        
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.email = "test@example.com"
        mock_user.name = "Test User"
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        db.execute.return_value = mock_result
        
        user = await auth_service.get_current_user(token)
        
        assert user.id == user_id
    
    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(self):
        """Should raise error for invalid token."""
        db = AsyncMock()
        auth_service = AuthService(db)
        
        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.get_current_user("invalid-token")
        
        assert "Invalid access token" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_current_user_refresh_token_rejected(self):
        """Should reject refresh token used as access token."""
        db = AsyncMock()
        auth_service = AuthService(db)
        
        user_id = "user-789"
        refresh_token, _ = auth_service._create_refresh_token(user_id)
        
        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.get_current_user(refresh_token)
        
        assert "Invalid token type" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_current_user_expired_token(self):
        """Should raise error for expired token."""
        db = AsyncMock()
        auth_service = AuthService(db)
        
        # Create token that's already expired
        user_id = "user-expired"
        token = auth_service._create_access_token(
            user_id,
            expires_delta=timedelta(seconds=-10),  # Already expired
        )
        
        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.get_current_user(token)
        
        assert "Invalid access token" in str(exc_info.value)


class TestLogout:
    """Tests for user logout."""
    
    @pytest.mark.asyncio
    async def test_logout_deletes_sessions(self):
        """Logout should delete all user sessions."""
        db = AsyncMock()
        
        # Mock sessions
        mock_session1 = MagicMock()
        mock_session2 = MagicMock()
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_session1, mock_session2]
        db.execute.return_value = mock_result
        
        auth_service = AuthService(db)
        
        await auth_service.logout("user-123")
        
        # Verify both sessions were deleted
        assert db.delete.call_count == 2
        db.flush.assert_called_once()


class TestRefreshToken:
    """Tests for token refresh."""
    
    @pytest.mark.asyncio
    async def test_refresh_token_success(self):
        """Should return new tokens for valid refresh token."""
        db = AsyncMock()
        auth_service = AuthService(db)
        
        user_id = "user-refresh-test"
        refresh_token, expires_at = auth_service._create_refresh_token(user_id)
        
        # Mock session with matching refresh token hash (using SHA-256)
        mock_session = MagicMock()
        mock_session.user_id = user_id
        mock_session.refresh_token_hash = auth_service._hash_token(refresh_token)
        mock_session.expires_at = expires_at
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_session]
        db.execute.return_value = mock_result
        
        new_tokens = await auth_service.refresh_token(refresh_token)
        
        assert isinstance(new_tokens, TokenPair)
        assert new_tokens.access_token is not None
        assert new_tokens.refresh_token is not None
        # Note: The new refresh token may be the same if generated in the same second
        # with the same expiry. The important thing is that a new session is created.
        
        # Verify old session deleted and new one created
        db.delete.assert_called_once_with(mock_session)
        db.add.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_refresh_token_invalid(self):
        """Should raise error for invalid refresh token."""
        db = AsyncMock()
        auth_service = AuthService(db)
        
        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.refresh_token("invalid-refresh-token")
        
        assert "Invalid refresh token" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_refresh_token_access_token_rejected(self):
        """Should reject access token used as refresh token."""
        db = AsyncMock()
        auth_service = AuthService(db)
        
        user_id = "user-wrong-type"
        access_token = auth_service._create_access_token(user_id)
        
        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.refresh_token(access_token)
        
        assert "Invalid token type" in str(exc_info.value)


class TestTokenPair:
    """Tests for TokenPair class."""
    
    def test_token_pair_creation(self):
        """TokenPair should store all token information."""
        token_pair = TokenPair(
            access_token="access123",
            refresh_token="refresh456",
            token_type="bearer",
            expires_in=1800,
        )
        
        assert token_pair.access_token == "access123"
        assert token_pair.refresh_token == "refresh456"
        assert token_pair.token_type == "bearer"
        assert token_pair.expires_in == 1800
    
    def test_token_pair_defaults(self):
        """TokenPair should have sensible defaults."""
        token_pair = TokenPair(
            access_token="access",
            refresh_token="refresh",
        )
        
        assert token_pair.token_type == "bearer"
        assert token_pair.expires_in == 0
