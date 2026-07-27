import hashlib
import secrets
import logging
from typing import Dict
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

logger = logging.getLogger(__name__)
security = HTTPBearer()

# In-memory mapping of active session tokens to usernames
ACTIVE_SESSIONS: Dict[str, str] = {}

class LoginRequest(BaseModel):
    username: str
    password: str

def hash_password(password: str) -> str:
    """Hashes a password using PBKDF2 with a random salt."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"{salt}:{key.hex()}"

def verify_password(stored_password: str, provided_password: str) -> bool:
    """Verifies a provided password against the stored salt:hash combination."""
    try:
        salt, stored_key = stored_password.split(":")
        key = hashlib.pbkdf2_hmac(
            'sha256',
            provided_password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return secrets.compare_digest(key.hex(), stored_key)
    except Exception:
        return False

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """FastAPI dependency to validate the Bearer session token in requests."""
    token = credentials.credentials
    if token not in ACTIVE_SESSIONS:
        logger.warning("Unauthenticated API access attempt blocked.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ACTIVE_SESSIONS[token]
