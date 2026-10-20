"""
app/utils.py — Shared utility functions for sanitization and text processing.
"""

import re


def sanitize_error(message: str) -> str:
    """
    Remove connection credentials or sensitive URI patterns from error messages.
    Truncates to 500 characters to keep database fields and logs bounded.
    """
    if not message:
        return ""
    cleaned = re.sub(r"://[^@]+@", "://***:***@", message)
    return cleaned[:500]
