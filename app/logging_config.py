"""
app/logging_config.py — Structured logging, request correlation, and secret redaction.

Milestone 10: Production Readiness.

Design Decisions
----------------
1. **Correlation / Request ID**:
   Uses Python's ``contextvars`` to bind an immutable ``request_id`` to each incoming request,
   propagating it automatically across async boundaries into every log statement.
2. **JSON & Human-Readable Formats**:
   - In production (``LOG_FORMAT=json``), outputs single-line JSON records containing timestamp,
     log level, logger name, request ID, and message, compatible with Datadog, GCP Cloud Logging,
     AWS CloudWatch, and Elasticsearch.
   - In development (``LOG_FORMAT=text``), outputs readable colored or formatted console lines.
3. **Secret Redaction**:
   Automatically sanitizes common secret patterns (API keys, bearer tokens, DB passwords)
   from outgoing log streams before they are emitted.
"""

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import re
import sys
from typing import Any, Dict
import uuid

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

# Safe request ID validation pattern: 1 to 64 alphanumeric characters, underscores, hyphens, and dots
REQUEST_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{1,64}$")


def sanitize_request_id(incoming: str | None) -> str:
    """
    Validate and sanitize an incoming request ID.

    Accepts alphanumeric, hyphen, underscore, and dot characters with length 1 to 64.
    If the incoming value is missing, exceeds 64 characters, or contains invalid characters,
    generates a clean UUIDv4.
    """
    if incoming and isinstance(incoming, str):
        trimmed = incoming.strip()
        if 1 <= len(trimmed) <= 64 and REQUEST_ID_REGEX.match(trimmed):
            return trimmed
    return str(uuid.uuid4())


# Regex patterns for sensitive data redaction
REDACTION_PATTERNS = [
    (re.compile(r"(gsk_[a-zA-Z0-9]{30,})"), "[REDACTED_GROQ_KEY]"),
    (re.compile(r"(sk-[a-zA-Z0-9]{20,})"), "[REDACTED_API_KEY]"),
    (re.compile(r"(Bearer\s+)[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE), r"\1[REDACTED_TOKEN]"),
    (re.compile(r"(eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})"), "[REDACTED_JWT]"),
    (re.compile(r"(X-API-Key:\s*)[^\s,]+", re.IGNORECASE), r"\1[REDACTED_KEY]"),
    (re.compile(r"(postgresql\+[a-z0-9]+://[^:]+:)([^@]+)(@)", re.IGNORECASE), r"\1***\3"),
    (re.compile(r'(["\']?password["\']?\s*[:=]\s*["\'])([^"\']*)(["\'])', re.IGNORECASE), r"\1[REDACTED]\3"),
    (re.compile(r'(["\']?hashed_password["\']?\s*[:=]\s*["\'])([^"\']*)(["\'])', re.IGNORECASE), r"\1[REDACTED]\3"),
    (re.compile(r"password=([^\s&]+)", re.IGNORECASE), "password=[REDACTED]"),
]


def redact_sensitive_text(text: str) -> str:
    """Strip API keys, tokens, and credentials from log messages."""
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RequestIdFilter(logging.Filter):
    """Injects current correlation request_id into all LogRecords."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get("-")
        return True


class JsonFormatter(logging.Formatter):
    """
    Structured JSON log formatter for containerized production log collection.
    """

    def format(self, record: logging.LogRecord) -> str:
        req_id = getattr(record, "request_id", "-")
        raw_msg = record.getMessage()
        safe_msg = redact_sensitive_text(raw_msg)

        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": req_id,
            "message": safe_msg,
        }

        if record.exc_info:
            log_entry["exception"] = redact_sensitive_text(
                self.formatException(record.exc_info)
            )

        return json.dumps(log_entry)


class TextFormatter(logging.Formatter):
    """Clean human-readable formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        req_id = getattr(record, "request_id", "-")
        raw_msg = super().format(record)
        safe_msg = redact_sensitive_text(raw_msg)
        return f"[{req_id}] {safe_msg}"


def setup_logging(level: str = "INFO", log_format: str = "json") -> None:
    """
    Configure global root logger with structured formatting and correlation filtering.
    """
    root_logger = logging.getLogger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.addFilter(RequestIdFilter())

    if log_format.lower() == "json":
        stream_handler.setFormatter(JsonFormatter())
    else:
        stream_handler.setFormatter(
            TextFormatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root_logger.addHandler(stream_handler)
    # Quiet noisy external libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
