"""
app/services/fingerprint.py — Deterministic error message fingerprinting.

Milestone 7: Incident grouping and event correlation.

Design Principles
-----------------
1. **Deterministic Grouping**: Identical errors across identical services and
   environments must always yield the exact same SHA-256 fingerprint.
2. **Selective Volatility Normalization**:
   Only replace volatile runtime artifacts (UUIDs, memory addresses, timestamps,
   IP addresses, specific entity IDs).
   DO NOT indiscriminately wipe numbers like HTTP status codes (404, 500),
   database error codes, or semantic message content.
3. **Collision Resistance**:
   Using SHA-256 hex digests (64 characters) guarantees collision-free indexing.
"""

import hashlib
import re

# ---------------------------------------------------------------------------
# Regex patterns for volatile values
# ---------------------------------------------------------------------------

# Standard 8-4-4-4-12 UUIDs
_UUID_REGEX = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

# Hexadecimal memory pointers (e.g. 0x7ffd58e1, 0x0000000104a3b890)
_HEX_REGEX = re.compile(r"\b0x[0-9a-fA-F]+\b")

# ISO-8601 Datetime strings (e.g. 2026-10-20T17:30:00Z, 2024-06-15 14:30:00.123)
_DATETIME_REGEX = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"
)

# IPv4 Addresses (e.g. 192.168.1.1, 10.0.0.24)
_IP_REGEX = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")

# Common entity identifiers in query strings or logs (e.g. user_id=12345, id=987)
_ENTITY_ID_PARAM_REGEX = re.compile(
    r"([?&/,\s](?:id|user_id|order_id|account_id|customer_id|session_id)=)\d+\b",
    re.IGNORECASE,
)

# REST-style numeric path segments (e.g. /users/12345 -> /users/<ID>)
_REST_PATH_ID_REGEX = re.compile(
    r"(/(?:users|orders|accounts|customers|sessions|items)/)\d+\b",
    re.IGNORECASE,
)


def normalize_error_message(message: str) -> str:
    """
    Normalize an error message by masking clearly volatile tokens with placeholders.

    Preserves semantic content, error names, and status codes (e.g. HTTP 404, 500).

    Examples
    --------
    >>> normalize_error_message("User 550e8400-e29b-41d4-a716-446655440000 failed at 0x7fff")
    'User <UUID> failed at <HEX>'
    >>> normalize_error_message("Connection timeout to 192.168.1.10 at 2026-10-20T17:30:00Z")
    'Connection timeout to <IP> at <DATETIME>'
    """
    if not message:
        return ""

    # Replace volatile patterns in sequence
    normalized = _UUID_REGEX.sub("<UUID>", message)
    normalized = _HEX_REGEX.sub("<HEX>", normalized)
    normalized = _DATETIME_REGEX.sub("<DATETIME>", normalized)
    normalized = _IP_REGEX.sub("<IP>", normalized)
    normalized = _ENTITY_ID_PARAM_REGEX.sub(r"\g<1><ID>", normalized)
    normalized = _REST_PATH_ID_REGEX.sub(r"\g<1><ID>", normalized)

    # Normalize whitespace: collapse newlines, tabs, and multiple spaces
    normalized = " ".join(normalized.strip().split())

    return normalized


def generate_fingerprint(service_name: str, environment: str, message: str) -> str:
    """
    Generate a deterministic 64-character SHA-256 fingerprint for grouping.

    Parameters
    ----------
    service_name : str
        Source microservice.
    environment : str
        Deployment environment (e.g. production, staging).
    message : str
        Raw event error message.

    Returns
    -------
    str
        64-character lowercase SHA-256 hex digest.
    """
    normalized_sig = normalize_error_message(message)
    canonical_string = f"{service_name.strip().lower()}:{environment.strip().lower()}:{normalized_sig}"
    return hashlib.sha256(canonical_string.encode("utf-8")).hexdigest()


def extract_incident_title(message: str, max_length: int = 120) -> str:
    """
    Derive a concise, readable incident title from an error message.

    Extracts the first line or up to max_length characters with normalized tokens.
    """
    if not message:
        return "Unknown Error Incident"

    # Take first line before whitespace collapsing
    first_line = message.split("\n")[0].strip()
    normalized = normalize_error_message(first_line)
    if not normalized:
        return "Unknown Error Incident"

    if len(normalized) > max_length:
        return normalized[:max_length].rstrip() + "..."
    return normalized
