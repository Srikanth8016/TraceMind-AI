"""
app/services/user_service.py — Service layer for User registration and authentication.

Milestone 14: Authentication & Authorization.
"""

from datetime import datetime, timezone
import logging
import uuid

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate
from app.security import hash_password, verify_password

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class UserServiceError(Exception):
    """Base domain exception for user operations."""
    pass


class UserAlreadyExistsError(UserServiceError):
    """Raised when a user registration conflicts with an existing email."""
    pass


class UserNotFoundError(UserServiceError):
    """Raised when a user cannot be found by ID."""
    pass


class UserInactiveError(UserServiceError):
    """Raised when an inactive user attempts to authenticate."""
    pass


class InvalidCredentialsError(UserServiceError):
    """Raised when email/password authentication fails."""
    pass


# ---------------------------------------------------------------------------
# User Service
# ---------------------------------------------------------------------------

class UserService:
    """
    Encapsulates all database operations and business logic related to Users.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        """Retrieve a user by their UUID primary key."""
        return self.db.get(User, user_id)

    def get_user_by_email(self, email: str) -> User | None:
        """Retrieve a user by their normalized email address."""
        normalized = email.strip().lower()
        stmt = select(User).where(User.email == normalized)
        return self.db.execute(stmt).scalars().first()

    def create_user(self, user_in: UserCreate) -> User:
        """
        Register and persist a new User in the database.

        Parameters
        ----------
        user_in : UserCreate
            Validated registration input containing email and password.

        Returns
        -------
        User
            The newly created and persisted User record.

        Raises
        ------
        UserAlreadyExistsError
            If a user with this email already exists or conflicts on commit.
        """
        normalized_email = user_in.email.strip().lower()

        # Pre-check email existence
        if self.get_user_by_email(normalized_email) is not None:
            logger.warning("Registration rejected: email %r already exists.", normalized_email)
            raise UserAlreadyExistsError(f"User with email '{normalized_email}' is already registered.")

        hashed = hash_password(user_in.password)
        now = datetime.now(timezone.utc)

        user = User(
            id=uuid.uuid4(),
            email=normalized_email,
            hashed_password=hashed,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        try:
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            logger.info("Successfully registered new user %s (email=%r)", user.id, user.email)
            return user
        except IntegrityError as exc:
            self.db.rollback()
            logger.warning("Integrity conflict creating user with email %r: %s", normalized_email, exc)
            raise UserAlreadyExistsError(f"User with email '{normalized_email}' is already registered.") from exc
        except SQLAlchemyError as exc:
            self.db.rollback()
            logger.error("Database error creating user: %s", exc, exc_info=True)
            raise UserServiceError("Database operation failed while creating user.") from exc
        except Exception:
            self.db.rollback()
            raise

    def authenticate_user(self, email: str, password: str) -> User:
        """
        Authenticate a user by email and plaintext password.

        Returns
        -------
        User
            The authenticated active User record.

        Raises
        ------
        InvalidCredentialsError
            If email is not found or password does not match.
        UserInactiveError
            If the account is disabled.
        """
        normalized_email = email.strip().lower()
        user = self.get_user_by_email(normalized_email)

        # Constant-time security: always verify password even if user is None (timing attack guard)
        if user is None:
            # Dummy verify to equalize response time
            verify_password(password, "pbkdf2_sha256$600000$00000000000000000000000000000000$0000000000000000000000000000000000000000000000000000000000000000")
            raise InvalidCredentialsError("Invalid email or password.")

        if not verify_password(password, user.hashed_password):
            logger.warning("Failed login attempt for email %r", normalized_email)
            raise InvalidCredentialsError("Invalid email or password.")

        if not user.is_active:
            logger.warning("Login rejected for inactive user %s (%r)", user.id, user.email)
            raise UserInactiveError("User account is inactive. Please contact system support.")

        logger.info("Successfully authenticated user %s (%r)", user.id, user.email)
        return user


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    """FastAPI dependency provider for UserService."""
    return UserService(db)
