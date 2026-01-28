"""Encryption service for secure API key storage using Fernet."""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class EncryptionError(Exception):
    """Raised when encryption or decryption fails."""
    pass


class EncryptionService:
    """Service for encrypting and decrypting sensitive data using Fernet.
    
    Fernet guarantees that a message encrypted using it cannot be manipulated
    or read without the key. It uses AES-128-CBC with PKCS7 padding and
    HMAC-SHA256 for authentication.
    
    The encryption key should be a URL-safe base64-encoded 32-byte key.
    Generate with: Fernet.generate_key()
    """
    
    def __init__(self, encryption_key: str | None = None):
        """Initialize EncryptionService with encryption key.
        
        Args:
            encryption_key: Fernet encryption key. If not provided,
                           uses settings.encryption_key.
                           
        Raises:
            EncryptionError: If encryption key is not configured or invalid.
        """
        key = encryption_key or settings.encryption_key
        
        if not key:
            raise EncryptionError(
                "Encryption key not configured. "
                "Set ENCRYPTION_KEY environment variable. "
                "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except Exception as e:
            raise EncryptionError(f"Invalid encryption key: {e}")
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string.
        
        Args:
            plaintext: String to encrypt
            
        Returns:
            Base64-encoded encrypted string
            
        Raises:
            EncryptionError: If encryption fails
        """
        if not plaintext:
            raise EncryptionError("Cannot encrypt empty string")
        
        try:
            encrypted_bytes = self._fernet.encrypt(plaintext.encode("utf-8"))
            return encrypted_bytes.decode("utf-8")
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {e}")
    
    def decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted string.
        
        Args:
            ciphertext: Base64-encoded encrypted string
            
        Returns:
            Decrypted plaintext string
            
        Raises:
            EncryptionError: If decryption fails (invalid key or corrupted data)
        """
        if not ciphertext:
            raise EncryptionError("Cannot decrypt empty string")
        
        try:
            decrypted_bytes = self._fernet.decrypt(ciphertext.encode("utf-8"))
            return decrypted_bytes.decode("utf-8")
        except InvalidToken:
            raise EncryptionError(
                "Decryption failed: Invalid token. "
                "The data may be corrupted or encrypted with a different key."
            )
        except Exception as e:
            raise EncryptionError(f"Decryption failed: {e}")


# Singleton instance for convenience
_encryption_service: EncryptionService | None = None


def get_encryption_service() -> EncryptionService:
    """Get or create the singleton EncryptionService instance.
    
    Returns:
        EncryptionService instance
        
    Raises:
        EncryptionError: If encryption key is not configured
    """
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service
