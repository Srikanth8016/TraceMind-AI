"""
app/schemas/user.py — Pydantic schemas for user registration, authentication, and responses.

Milestone 14: Authentication & Authorization.
"""

from datetime import datetime
import re
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


EMAIL_REGEX = re.compile(r"^[\w\.\+\-]+@[\w\-]+\.[a-zA-Z]{2,}$")


class UserCreate(BaseModel):
    """
    Schema for user registration via POST /auth/register.
    """
    email: str = Field(..., description="User email address.")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plaintext password (minimum 8 characters, maximum 128 characters).",
    )

    @field_validator("email", mode="before")
    @classmethod
    def validate_and_normalize_email(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Email must be a string.")
        cleaned = v.strip().lower()
        if not cleaned or not EMAIL_REGEX.match(cleaned):
            raise ValueError("Invalid email format.")
        return cleaned


class UserLogin(BaseModel):
    """
    Schema for user authentication via POST /auth/login.
    """
    email: str = Field(..., description="User email address.")
    password: str = Field(..., description="User password.")

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return v


class UserResponse(BaseModel):
    """
    Public representation of a User record (never leaks password hashes).
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Unique user identifier.")
    email: str = Field(..., description="Normalized user email.")
    is_active: bool = Field(..., description="Account active status.")
    created_at: datetime = Field(..., description="Timestamp of user account creation.")
    updated_at: datetime = Field(..., description="Timestamp of user account last update.")


class Token(BaseModel):
    """
    JWT authentication bearer token response.
    """
    access_token: str = Field(..., description="Signed JWT access token.")
    token_type: str = Field(default="bearer", description="Token type (Bearer).")


class TokenData(BaseModel):
    """
    Extracted JWT payload claims.
    """
    user_id: uuid.UUID | None = None
    email: str | None = None
