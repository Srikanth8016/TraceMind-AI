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
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

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
