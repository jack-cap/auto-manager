"""Authentication service for user management and JWT tokens."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import Session, User

# Password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenPair:
    """Container for access and refresh token pair."""
    
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_type: str = "bearer",
        expires_in: int = 0,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = token_type
        self.expires_in = expires_in


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


class AuthService:
    """Service for handling user authentication and session management.
    
    Provides methods for:
    - User registration and login
    - Password hashing and verification
    - JWT token generation and validation
    - Session management with refresh tokens
    """
    
    def __init__(self, db: AsyncSession):
        """Initialize AuthService with database session.
        
        Args:
            db: Async SQLAlchemy session
        """
        self.db = db
    
    def hash_password(self, password: str) -> str:
        """Hash a plaintext password using bcrypt.
        
        Args:
            password: Plaintext password to hash
            
        Returns:
            Bcrypt hashed password string
        """
        return pwd_context.hash(password)
    
    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify a password against its hash.
        
        Args:
            password: Plaintext password to verify
            hashed: Bcrypt hashed password to compare against
            
        Returns:
            True if password matches, False otherwise
        """
        return pwd_context.verify(password, hashed)
    
    def _hash_token(self, token: str) -> str:
        """Hash a token using SHA-256.
        
        Unlike bcrypt, SHA-256 handles arbitrary length inputs without truncation.
        This is important for JWT tokens which exceed bcrypt's 72-byte limit.
        
        Args:
            token: Token string to hash
            
        Returns:
            Hex-encoded SHA-256 hash
        """
        return hashlib.sha256(token.encode()).hexdigest()
    
    def _verify_token_hash(self, token: str, hashed: str) -> bool:
        """Verify a token against its SHA-256 hash.
        
        Uses constant-time comparison to prevent timing attacks.
        
        Args:
            token: Token to verify
            hashed: SHA-256 hash to compare against
            
        Returns:
            True if token matches hash, False otherwise
        """
        return secrets.compare_digest(self._hash_token(token), hashed)
    
    def _create_access_token(
        self,
        user_id: str,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """Create a JWT access token.
        
        Args:
            user_id: User ID to encode in token
            expires_delta: Optional custom expiration time
            
        Returns:
            Encoded JWT access token string
        """
        if expires_delta is None:
            expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
        
        expire = datetime.now(timezone.utc) + expires_delta
        to_encode = {
            "sub": user_id,
            "exp": expire,
            "type": "access",
        }
        
        return jwt.encode(
            to_encode,
            settings.secret_key,
            algorithm=settings.jwt_algorithm,
        )
    
    def _create_refresh_token(
        self,
        user_id: str,
        expires_delta: Optional[timedelta] = None,
    ) -> tuple[str, datetime]:
        """Create a JWT refresh token.
        
        Args:
            user_id: User ID to encode in token
            expires_delta: Optional custom expiration time
            
        Returns:
            Tuple of (encoded JWT refresh token, expiration datetime)
        """
        if expires_delta is None:
            expires_delta = timedelta(days=settings.refresh_token_expire_days)
        
        expire = datetime.now(timezone.utc) + expires_delta
        to_encode = {
            "sub": user_id,
            "exp": expire,
            "type": "refresh",
        }
        
        token = jwt.encode(
            to_encode,
            settings.secret_key,
            algorithm=settings.jwt_algorithm,
        )
        
        return token, expire
    
    async def register(
        self,
        email: str,
        password: str,
        name: str,
    ) -> User:
        """Register a new user.
        
        Args:
            email: User's email address (must be unique)
            password: Plaintext password (will be hashed)
            name: User's display name
            
        Returns:
            Created User instance
            
        Raises:
            AuthenticationError: If email already exists
        """
        # Check if email already exists
        existing = await self.db.execute(
            select(User).where(User.email == email)
        )
        if existing.scalar_one_or_none():
            raise AuthenticationError("Email already registered")
        
        # Create new user with hashed password
        user = User(
            email=email,
            password_hash=self.hash_password(password),
            name=name,
        )
        
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        
        return user
    
    async def login(self, email: str, password: str) -> TokenPair:
        """Authenticate user and create session.
        
        Args:
            email: User's email address
            password: Plaintext password
            
        Returns:
            TokenPair with access and refresh tokens
            
        Raises:
            AuthenticationError: If credentials are invalid
        """
        # Find user by email
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        if not user or not self.verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid email or password")
        
        # Create tokens
        access_token = self._create_access_token(user.id)
        refresh_token, expires_at = self._create_refresh_token(user.id)
        
        # Store session with hashed refresh token
        session = Session(
            user_id=user.id,
            refresh_token_hash=self._hash_token(refresh_token),
            expires_at=expires_at,
        )
        self.db.add(session)
        await self.db.flush()
        
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.access_token_expire_minutes * 60,
        )
    
    async def refresh_token(self, refresh_token: str) -> TokenPair:
        """Refresh access token using refresh token.
        
        Args:
            refresh_token: Valid refresh token
            
        Returns:
            New TokenPair with fresh access and refresh tokens
            
        Raises:
            AuthenticationError: If refresh token is invalid or expired
        """
        try:
            # Decode and validate refresh token
            payload = jwt.decode(
                refresh_token,
                settings.secret_key,
                algorithms=[settings.jwt_algorithm],
            )
            
            if payload.get("type") != "refresh":
                raise AuthenticationError("Invalid token type")
            
            user_id = payload.get("sub")
            if not user_id:
                raise AuthenticationError("Invalid token payload")
            
        except JWTError as e:
            raise AuthenticationError(f"Invalid refresh token: {str(e)}")
        
        # Find valid session for this user
        result = await self.db.execute(
            select(Session).where(
                Session.user_id == user_id,
                Session.expires_at > datetime.now(timezone.utc),
            )
        )
        sessions = result.scalars().all()
        
        # Verify refresh token against stored hashes
        valid_session = None
        for session in sessions:
            if self._verify_token_hash(refresh_token, session.refresh_token_hash):
                valid_session = session
                break
        
        if not valid_session:
            raise AuthenticationError("Refresh token not found or expired")
        
        # Delete old session
        await self.db.delete(valid_session)
        
        # Create new tokens
        access_token = self._create_access_token(user_id)
        new_refresh_token, expires_at = self._create_refresh_token(user_id)
        
        # Store new session
        new_session = Session(
            user_id=user_id,
            refresh_token_hash=self._hash_token(new_refresh_token),
            expires_at=expires_at,
        )
        self.db.add(new_session)
        await self.db.flush()
        
        return TokenPair(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=settings.access_token_expire_minutes * 60,
        )
    
    async def logout(self, user_id: str) -> None:
        """Invalidate all sessions for a user.
        
        Args:
            user_id: ID of user to logout
        """
        result = await self.db.execute(
            select(Session).where(Session.user_id == user_id)
        )
        sessions = result.scalars().all()
        
        for session in sessions:
            await self.db.delete(session)
        
        await self.db.flush()
    
    async def get_current_user(self, token: str) -> User:
        """Get user from access token.
        
        Args:
            token: JWT access token
            
        Returns:
            User instance
            
        Raises:
            AuthenticationError: If token is invalid or user not found
        """
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.jwt_algorithm],
            )
            
            if payload.get("type") != "access":
                raise AuthenticationError("Invalid token type")
            
            user_id = payload.get("sub")
            if not user_id:
                raise AuthenticationError("Invalid token payload")
            
        except JWTError as e:
            raise AuthenticationError(f"Invalid access token: {str(e)}")
        
        # Get user from database
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise AuthenticationError("User not found")
        
        return user
    
    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID.
        
        Args:
            user_id: User's UUID
            
        Returns:
            User instance or None if not found
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email.
        
        Args:
            email: User's email address
            
        Returns:
            User instance or None if not found
        """
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()
