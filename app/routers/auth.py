"""
app/routers/auth.py — Router for user registration, login, and profile operations.

Milestone 14: Authentication & Authorization.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_active_user
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserLogin, UserResponse
from app.security import create_access_token
from app.services.user_service import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
    UserInactiveError,
    UserService,
    get_user_service,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
    description=(
        "Register a new user account with a unique normalized email address and secure password. "
        "Passwords are cryptographically hashed using Argon2 / PBKDF2 before storage."
    ),
)
def register(
    user_in: UserCreate,
    user_service: UserService = Depends(get_user_service),
) -> UserResponse:
    """
    Register a new user account.
    """
    try:
        user = user_service.create_user(user_in)
        return user
    except UserAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/login",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="User login and JWT access token issuance",
    description=(
        "Authenticate using normalized email and password. "
        "Returns a signed JWT bearer access token on success. "
        "Returns HTTP 401 for invalid credentials or inactive accounts."
    ),
)
def login(
    credentials_in: UserLogin,
    user_service: UserService = Depends(get_user_service),
) -> Token:
    """
    Authenticate user and issue JWT access token.
    """
    try:
        user = user_service.authenticate_user(
            email=credentials_in.email,
            password=credentials_in.password,
        )
    except UserInactiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive. Please contact system support.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    access_token = create_access_token(
        subject=str(user.id),
        extra_claims={"email": user.email},
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current authenticated user profile",
    description="Retrieve the profile of the active user associated with the Bearer access token.",
)
def get_me(
    current_user: User = Depends(get_current_active_user),
) -> UserResponse:
    """
    Return currently authenticated active user.
    """
    return current_user
