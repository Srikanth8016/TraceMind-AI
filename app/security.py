"""
app/security.py — Cryptographic utilities for password hashing and JWT management.

Milestone 14: Authentication & Authorization.
- Secure password hashing using Argon2 (with NIST SP 800-132 PBKDF2-HMAC-SHA256 fallback).
- RFC 7519 compliant JWT access token creation and verification.
- Constant-time secret comparisons to guard against timing side-channel attacks.
"""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import secrets
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# Try importing argon2-cffi if installed
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    _argon2_hasher = PasswordHasher()
    _HAS_ARGON2 = True
except ImportError:
    _argon2_hasher = None
    _HAS_ARGON2 = False

# Try importing pyjwt if installed
try:
    import jwt
    _HAS_PYJWT = True
except ImportError:
    _HAS_PYJWT = False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TokenError(Exception):
    """Base exception for token decoding failures."""
    pass


class TokenExpiredError(TokenError):
    """Raised when a JWT access token has expired."""
    pass


class TokenInvalidError(TokenError):
    """Raised when a JWT access token signature or format is invalid."""
    pass


# ---------------------------------------------------------------------------
# Password Hashing & Verification
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """
    Hash a plaintext password using Argon2id if available, or PBKDF2-HMAC-SHA256.

    Returns
    -------
    str
        Securely formatted password hash string.
    """
    if _HAS_ARGON2 and _argon2_hasher is not None:
        return _argon2_hasher.hash(password)

    # NIST SP 800-132 compliant PBKDF2-HMAC-SHA256 (600,000 rounds)
    salt = secrets.token_hex(16)
    iterations = 600000
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a stored hash string in constant time.
    """
    if not plain_password or not hashed_password:
        return False

    # 1. Argon2 format
    if hashed_password.startswith("$argon2"):
        if _HAS_ARGON2 and _argon2_hasher is not None:
            try:
                return _argon2_hasher.verify(hashed_password, plain_password)
            except VerifyMismatchError:
                return False
            except Exception:
                return False
        return False

    # 2. PBKDF2 format: pbkdf2_sha256$<iterations>$<salt>$<hash>
    if hashed_password.startswith("pbkdf2_sha256$"):
        parts = hashed_password.split("$")
        if len(parts) != 4:
            return False
        try:
            iterations = int(parts[1])
            salt = parts[2]
            expected_hex = parts[3]
            derived = hashlib.pbkdf2_hmac(
                "sha256",
                plain_password.encode("utf-8"),
                salt.encode("utf-8"),
                iterations,
            )
            return secrets.compare_digest(derived.hex(), expected_hex)
        except Exception:
            return False

    return False


# ---------------------------------------------------------------------------
# JWT Access Token Management
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(
    subject: str | None = None,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Parameters
    ----------
    subject : str, optional
        The subject identifier (user UUID as string).
    extra_claims : dict, optional
        Additional claims to encode into the token payload.
    expires_delta : timedelta, optional
        Custom expiration delta. Defaults to Settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES.
    data : dict, optional
        Alternative dictionary containing 'sub' and extra claims.

    Returns
    -------
    str
        Signed JWT string.
    """
    settings = get_settings()
    secret = getattr(settings, "JWT_SECRET_KEY", "dev-jwt-secret-key-32bytes-long-change-in-prod")
    algorithm = getattr(settings, "JWT_ALGORITHM", "HS256")

    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire_minutes = getattr(settings, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 60)
        expire = now + timedelta(minutes=expire_minutes)

    sub_val = subject
    payload: dict[str, Any] = {}
    if data:
        payload.update(data)
        if "sub" in data and not sub_val:
            sub_val = str(data["sub"])

    payload["sub"] = str(sub_val or "")
    payload["iat"] = int(now.timestamp())
    payload["exp"] = int(expire.timestamp())

    if extra_claims:
        payload.update(extra_claims)

    if _HAS_PYJWT:
        return jwt.encode(payload, secret, algorithm=algorithm)

    # Standard RFC 7519 HS256 JWT encoding
    header = {"alg": "HS256", "typ": "JWT"}
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    header_b64 = _b64url_encode(header_bytes)
    payload_b64 = _b64url_encode(payload_bytes)

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Validate and decode a signed JWT access token.

    Parameters
    ----------
    token : str
        The JWT access token string.

    Returns
    -------
    dict
        Decoded payload dictionary.

    Raises
    ------
    TokenExpiredError
        If the token's exp claim has passed.
    TokenInvalidError
        If signature verification fails or token format is invalid.
    """
    settings = get_settings()
    secret = getattr(settings, "JWT_SECRET_KEY", "dev-jwt-secret-key-32bytes-long-change-in-prod")
    algorithm = getattr(settings, "JWT_ALGORITHM", "HS256")

    if _HAS_PYJWT:
        try:
            return jwt.decode(token, secret, algorithms=[algorithm])
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError("Token has expired.") from exc
        except jwt.PyJWTError as exc:
            raise TokenInvalidError("Invalid or malformed token.") from exc

    # Standard RFC 7519 HS256 JWT decoding
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenInvalidError("Invalid token format.")

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()

    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception as exc:
        raise TokenInvalidError("Invalid base64 encoding in signature.") from exc

    if not secrets.compare_digest(expected_sig, actual_sig):
        raise TokenInvalidError("Signature verification failed.")

    try:
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise TokenInvalidError("Invalid payload JSON.") from exc

    # Validate exp claim
    exp = payload.get("exp")
    if exp is not None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if now_ts >= int(exp):
            raise TokenExpiredError("Token has expired.")

    return payload
