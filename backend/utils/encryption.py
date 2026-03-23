import os
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger(__name__)

# The master key should be generated once and stored in the .env file
# To generate a new one: Fernet.generate_key().decode()
FERNET_KEY = os.getenv("FERNET_KEY")
_fernet = None

if FERNET_KEY:
    try:
        _fernet = Fernet(FERNET_KEY.encode())
    except Exception as e:
        logger.error(f"Failed to initialize encryption: {e}")
        _fernet = None

def encrypt_value(value: str) -> str:
    """Encrypts a string value for secure database storage."""
    if not value:
        return value
    if not _fernet:
        logger.warning("FERNET_KEY not set or invalid. Storing value as plain text!")
        return value
    try:
        return _fernet.encrypt(value.encode()).decode()
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return value

def decrypt_value(encrypted_value: str) -> str:
    """Decrypts a securely stored database string."""
    if not encrypted_value:
        return encrypted_value
    
    # If it wasn't encrypted (e.g. from before encryption was added), just return it
    if not encrypted_value.startswith('gAAAAA'):
        return encrypted_value
        
    if not _fernet:
        logger.error("Attempting to decrypt but no FERNET_KEY configured!")
        return ""
        
    try:
        return _fernet.decrypt(encrypted_value.encode()).decode()
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return ""
import hmac
import hashlib

def generate_blind_index(value: str) -> str:
    """ Generates a deterministic hash for indexing/searching encrypted values. """
    if not value:
        return ""
    # We use SECRET_KEY as a salt for the blind index
    salt = os.getenv("SECRET_KEY", "default_salt_for_indexing").encode()
    return hmac.new(salt, value.lower().strip().encode(), hashlib.sha256).hexdigest()
