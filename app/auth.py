"""
app/auth.py — API-Key authentication dependency and security schemes.

Milestone 5: API-Key authentication and endpoint protection.

Design principles
-----------------
1. **Header-based authentication**: Reads ``X-API-Key`` from request headers.
2. **Fail closed**: If the server environment variable ``TRACEMIND_API_KEY``
   is missing or empty, protected routes return HTTP 500 (Internal Server Error)
   rather than silently letting requests through.
3. **Constant-time comparison**: Uses ``secrets.compare_digest`` to prevent
   timing attacks on secret comparisons.
4. **OpenAPI integration**: Uses ``APIKeyHeader`` so Swagger UI (/docs)
   renders the security scheme and "Authorize" button.
5. **No secret leakage**: Keys are never logged, reflected in errors, or committed.
"""

import os
import secrets
import uuid

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.security import (
    TokenError,
    TokenExpiredError,
    TokenInvalidError,
    decode_access_token,
)

# ---------------------------------------------------------------------------
# OpenAPI Security Scheme
# ---------------------------------------------------------------------------
# auto_error=False allows our dependency to inspect missing headers and raise
# HTTP 401 with a consistent custom message, rather than FastAPI's default 403.
api_key_header_scheme = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Secret API key required to access protected TraceMind AI endpoints.",
)


def get_configured_api_key() -> str | None:
    """
    Retrieve the configured API key from the environment.

    Returns the stripped string if non-empty, or None if unset/empty.
    """
    raw_key = os.environ.get("TRACEMIND_API_KEY")
    if raw_key is not None:
        trimmed = raw_key.strip()
        if trimmed:
            return trimmed
    return None


def verify_api_key(
    client_api_key: str | None = Security(api_key_header_scheme),
) -> str:
    """
    FastAPI dependency that enforces API key authentication.

    Raises
    ------
    HTTPException(500)
        If the server administrator has not configured TRACEMIND_API_KEY.
        (Fails closed to prevent accidental open access in production).
    HTTPException(401)
        If the client omitted X-API-Key or supplied an incorrect key.
        Uses constant-time comparison (secrets.compare_digest).

    Returns
    -------
    str
        The verified API key.
    """
    expected_key = get_configured_api_key()

    # Fail closed: server misconfiguration is an internal server error
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication is unconfigured on the server.",
        )

    # Missing client key
    if not client_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key.",
        )

    # Constant-time comparison to guard against timing attacks
    if not secrets.compare_digest(client_api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key.",
        )

    return client_api_key


# ---------------------------------------------------------------------------
# JWT Bearer Token Security Scheme (Milestone 14)
# ---------------------------------------------------------------------------

http_bearer_scheme = HTTPBearer(
    auto_error=False,
    description="JWT Bearer token required for user authentication. Example: Bearer <token>",
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(http_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Retrieve the authenticated User model from the Bearer token.

    Raises
    ------
    HTTPException(401)
        If token is missing, malformed, expired, invalidly signed, or user not found.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()
    try:
        payload = decode_access_token(token)
    except TokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (TokenInvalidError, TokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, malformed, or improperly signed token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing subject identifier.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed user identifier in token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, user_uuid)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account associated with this token does not exist.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    FastAPI dependency that enforces the authenticated user account is active.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user account.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user
