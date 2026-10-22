"""
app/services/incident_service.py — Service layer for Incident operations.

Milestone 12: Production-Ready Backend Architecture.
Implements the Service Layer pattern to decouple database queries and business
logic from FastAPI route handlers.

Architecture Flow:
Client HTTP Request -> Router -> Service Layer -> Database Session
"""

from datetime import datetime, timezone
import logging
from typing import Sequence
import uuid

from fastapi import Depends
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.event import Event
from app.models.incident import Incident, IncidentStatus
from app.schemas.incident import IncidentCreate, IncidentStatusUpdate, IncidentUpdate
from app.services.fingerprint import generate_fingerprint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class IncidentServiceError(Exception):
    """Base domain exception for IncidentService operations."""
    pass


class IncidentNotFoundError(IncidentServiceError):
    """Raised when an incident is not found by ID."""
    def __init__(self, incident_id: uuid.UUID) -> None:
        self.incident_id = incident_id
        super().__init__(f"Incident with id={incident_id!s} not found.")


class IncidentConflictError(IncidentServiceError):
    """Raised when an entity conflict or unique constraint violation occurs."""
    pass


class IncidentDatabaseError(IncidentServiceError):
    """Raised when an unrecoverable database error occurs, masking internal details."""
    pass


class IncidentValidationError(IncidentServiceError):
    """Raised when incident query parameters or payloads fail validation."""
    pass


class IncidentInvalidTransitionError(IncidentServiceError):
    """Raised when an illegal or unsupported incident lifecycle status transition is requested."""
    pass


# ---------------------------------------------------------------------------
# Allowed Workflow Status Transitions
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.OPEN: {
        IncidentStatus.OPEN,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.ACKNOWLEDGED,
        IncidentStatus.RESOLVED,
        IncidentStatus.CLOSED,
    },
    IncidentStatus.INVESTIGATING: {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.ACKNOWLEDGED,
        IncidentStatus.RESOLVED,
        IncidentStatus.CLOSED,
        IncidentStatus.OPEN,
    },
    IncidentStatus.ACKNOWLEDGED: {
        IncidentStatus.ACKNOWLEDGED,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.RESOLVED,
        IncidentStatus.CLOSED,
        IncidentStatus.OPEN,
    },
    IncidentStatus.RESOLVED: {
        IncidentStatus.RESOLVED,
        IncidentStatus.CLOSED,
        IncidentStatus.OPEN,  # Reopening a resolved incident
    },
    IncidentStatus.CLOSED: {
        IncidentStatus.CLOSED,
        IncidentStatus.OPEN,  # Explicitly reopening a closed incident
    },
}


def validate_status_transition(
    current_status: str | IncidentStatus,
    target_status: str | IncidentStatus,
) -> IncidentStatus:
    """
    Validate that transitioning from current_status to target_status is permitted.

    Parameters
    ----------
    current_status : str | IncidentStatus
        The current incident lifecycle status.
    target_status : str | IncidentStatus
        The proposed new lifecycle status.

    Returns
    -------
    IncidentStatus
        The validated target IncidentStatus enum member.

    Raises
    ------
    IncidentValidationError
        If target_status cannot be resolved to an IncidentStatus enum member.
    IncidentInvalidTransitionError
        If the transition is forbidden by ALLOWED_TRANSITIONS.
    """
    try:
        curr_enum = (
            current_status
            if isinstance(current_status, IncidentStatus)
            else IncidentStatus(str(current_status))
        )
    except ValueError:
        curr_enum = IncidentStatus.OPEN

    try:
        target_enum = (
            target_status
            if isinstance(target_status, IncidentStatus)
            else IncidentStatus(str(target_status))
        )
    except ValueError as exc:
        raise IncidentValidationError(f"Invalid incident status '{target_status}'.") from exc

    allowed = ALLOWED_TRANSITIONS.get(curr_enum, {curr_enum})
    if target_enum not in allowed:
        allowed_names = sorted([s.value for s in allowed])
        raise IncidentInvalidTransitionError(
            f"Cannot transition incident status from '{curr_enum.value}' to '{target_enum.value}'. "
            f"Allowed transitions from '{curr_enum.value}': {allowed_names}"
        )
    return target_enum


# ---------------------------------------------------------------------------
# Query Allowlist for Sorting
# ---------------------------------------------------------------------------

ALLOWED_SORT_COLUMNS = {
    "created_at": Incident.created_at,
    "last_seen_at": Incident.last_seen_at,
    "first_seen_at": Incident.first_seen_at,
    "severity": Incident.severity,
    "id": Incident.id,
    "title": Incident.title,
    "service_name": Incident.service_name,
    "event_count": Incident.event_count,
}


class IncidentService:
    """
    Encapsulates all database operations and business logic related to Incidents.
    
    Attributes
    ----------
    db : Session
        Active SQLAlchemy database session provided by dependency injection.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_incident(
        self,
        incident_in: IncidentCreate,
        owner_id: uuid.UUID | None = None,
    ) -> Incident:
        """
        Create and persist a new Incident in the database.

        Ensures atomic transaction management: commits the session on success,
        rolls back on failure, and refreshes the instance attributes.
        """
        now = datetime.now(timezone.utc)
        fingerprint = generate_fingerprint(
            service_name=incident_in.service_name,
            environment=incident_in.environment,
            message=incident_in.title,
        )
        status_val = (
            incident_in.status.value
            if isinstance(incident_in.status, IncidentStatus)
            else incident_in.status
        )

        incident = Incident(
            id=uuid.uuid4(),
            service_name=incident_in.service_name,
            environment=incident_in.environment,
            fingerprint=fingerprint,
            title=incident_in.title,
            severity=incident_in.severity,
            status=status_val,
            owner_id=owner_id,
            first_seen_at=now,
            last_seen_at=now,
            event_count=1,
            created_at=now,
            updated_at=now,
        )
        try:
            self.db.add(incident)
            self.db.commit()
            self.db.refresh(incident)
            logger.info("Successfully created incident %s (title=%r, owner_id=%s)", incident.id, incident.title, owner_id)
            return incident
        except IntegrityError as exc:
            self.db.rollback()
            logger.warning("Integrity conflict creating incident: %s", exc)
            raise IncidentConflictError(f"Incident with fingerprint '{fingerprint[:8]}' already exists or conflicts.") from exc
        except SQLAlchemyError as exc:
            self.db.rollback()
            logger.error("Database error during incident creation: %s", exc, exc_info=True)
            raise IncidentDatabaseError("Database operation failed while creating incident.") from exc
        except Exception as exc:
            self.db.rollback()
            logger.error("Unexpected failure during incident creation: %s", exc, exc_info=True)
            raise

    def update_incident_status(
        self,
        incident_id: uuid.UUID,
        new_status: IncidentStatus | str,
        owner_id: uuid.UUID | None = None,
    ) -> Incident:
        """
        Update the lifecycle status of an incident within an atomic transaction.

        Applies row locking to serialize concurrent status updates, commits the
        change, and updates the updated_at timestamp. Scoped to owner_id if provided.
        """
        try:
            # Row-level lock where supported to prevent concurrent lost updates
            stmt = select(Incident).where(Incident.id == incident_id)
            if owner_id is not None:
                stmt = stmt.where(Incident.owner_id == owner_id)
            incident = self.db.execute(stmt.with_for_update()).scalars().first()

            if incident is None:
                raise IncidentNotFoundError(incident_id)

            # Enforce workflow state machine transition rules
            target_status = validate_status_transition(incident.status, new_status)
            incident.status = target_status.value
            incident.updated_at = datetime.now(timezone.utc)

            self.db.commit()
            self.db.refresh(incident)
            logger.info("Updated incident %s status to %s", incident_id, target_status.value)
            return incident
        except (IncidentNotFoundError, IncidentInvalidTransitionError, IncidentValidationError):
            self.db.rollback()
            raise
        except IntegrityError as exc:
            self.db.rollback()
            logger.warning("Integrity error updating incident %s: %s", incident_id, exc)
            raise IncidentConflictError(f"Conflict updating status for incident {incident_id}.") from exc
        except SQLAlchemyError as exc:
            self.db.rollback()
            logger.error("Database error updating incident %s: %s", incident_id, exc, exc_info=True)
            raise IncidentDatabaseError("Database error occurred while updating incident status.") from exc
        except Exception:
            self.db.rollback()
            raise

    def update_incident(
        self,
        incident_id: uuid.UUID,
        incident_in: IncidentUpdate,
        owner_id: uuid.UUID | None = None,
    ) -> Incident:
        """
        Update supported fields of an existing incident within an atomic transaction.

        Applies row locking to serialize concurrent updates. Only fields that
        are explicitly provided (not None) are modified. Status updates enforce
        the same lifecycle workflow transition rules. Scoped to owner_id if provided.
        """
        try:
            stmt = select(Incident).where(Incident.id == incident_id)
            if owner_id is not None:
                stmt = stmt.where(Incident.owner_id == owner_id)
            incident = self.db.execute(stmt.with_for_update()).scalars().first()

            if incident is None:
                raise IncidentNotFoundError(incident_id)

            if incident_in.title is not None:
                incident.title = incident_in.title
            if incident_in.severity is not None:
                incident.severity = incident_in.severity
            if incident_in.status is not None:
                target_status = validate_status_transition(incident.status, incident_in.status)
                incident.status = target_status.value

            incident.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(incident)
            logger.info("Successfully updated incident %s", incident_id)
            return incident
        except (IncidentNotFoundError, IncidentInvalidTransitionError, IncidentValidationError):
            self.db.rollback()
            raise
        except IntegrityError as exc:
            self.db.rollback()
            logger.warning("Integrity conflict updating incident %s: %s", incident_id, exc)
            raise IncidentConflictError(f"Conflict updating incident {incident_id}.") from exc
        except SQLAlchemyError as exc:
            self.db.rollback()
            logger.error("Database error updating incident %s: %s", incident_id, exc, exc_info=True)
            raise IncidentDatabaseError("Database error occurred while updating incident.") from exc
        except Exception:
            self.db.rollback()
            raise

    def delete_incident(
        self,
        incident_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
    ) -> bool:
        """
        Delete an existing incident within an atomic transaction. Scoped to owner_id if provided.
        """
        try:
            stmt = select(Incident).where(Incident.id == incident_id)
            if owner_id is not None:
                stmt = stmt.where(Incident.owner_id == owner_id)
            incident = self.db.execute(stmt).scalars().first()
            if incident is None:
                raise IncidentNotFoundError(incident_id)

            self.db.delete(incident)
            self.db.commit()
            logger.info("Successfully deleted incident %s", incident_id)
            return True
        except IncidentNotFoundError:
            self.db.rollback()
            raise
        except SQLAlchemyError as exc:
            self.db.rollback()
            logger.error("Database error deleting incident %s: %s", incident_id, exc, exc_info=True)
            raise IncidentDatabaseError("Database error occurred while deleting incident.") from exc
        except Exception:
            self.db.rollback()
            raise

    def list_incidents(
        self,
        search: str | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        severity: str | None = None,
        status_filter: IncidentStatus | str | None = None,
        sort_by: str = "last_seen_at",
        order: str = "desc",
        limit: int = 20,
        offset: int = 0,
        owner_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[Incident], int]:
        """
        Query, filter, search, sort, and paginate incidents with deterministic ordering.
        Scoped to owner_id if provided.
        """
        stmt = select(Incident)

        # 0. User ownership scoping (allows system-correlated incidents with NULL owner_id)
        if owner_id is not None:
            stmt = stmt.where(or_(Incident.owner_id == owner_id, Incident.owner_id.is_(None)))

        # 1. Search by title (case-insensitive substring) and optional description
        if search is not None and search.strip():
            clean_search = search.strip()
            if hasattr(Incident, "description"):
                stmt = stmt.where(
                    or_(
                        Incident.title.ilike(f"%{clean_search}%"),
                        Incident.description.ilike(f"%{clean_search}%"),
                    )
                )
            else:
                stmt = stmt.where(Incident.title.ilike(f"%{clean_search}%"))

        # 2. Filters
        if service_name is not None and service_name.strip():
            stmt = stmt.where(Incident.service_name == service_name.strip())
        if environment is not None and environment.strip():
            stmt = stmt.where(Incident.environment == environment.strip())
        if severity is not None and severity.strip():
            stmt = stmt.where(func.lower(Incident.severity) == severity.strip().lower())
        if status_filter is not None:
            status_str = status_filter.value if isinstance(status_filter, IncidentStatus) else str(status_filter)
            stmt = stmt.where(func.upper(Incident.status) == status_str.strip().upper())

        # 3. Count total matching records before applying pagination limit/offset
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.db.scalar(count_stmt) or 0

        # 4. Sorting with deterministic tie-breaker
        sort_col_key = (sort_by.lower() if sort_by else "last_seen_at").strip()
        if sort_col_key not in ALLOWED_SORT_COLUMNS:
            raise IncidentValidationError(
                f"Invalid sort field '{sort_by}'. Allowed fields: {list(ALLOWED_SORT_COLUMNS.keys())}"
            )

        sort_column = ALLOWED_SORT_COLUMNS[sort_col_key]
        is_asc = (order or "desc").lower().strip() == "asc"

        if is_asc:
            stmt = stmt.order_by(sort_column.asc(), Incident.id.asc())
        else:
            stmt = stmt.order_by(sort_column.desc(), Incident.id.desc())

        stmt = stmt.limit(limit).offset(offset)

        items = self.db.execute(stmt).scalars().all()
        return items, total

    def get_incident_by_id(
        self,
        incident_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
    ) -> Incident | None:
        """
        Retrieve a single incident by its UUID primary key, optionally scoped to owner_id.

        Parameters
        ----------
        incident_id : uuid.UUID
            The unique identifier of the incident.
        owner_id : uuid.UUID | None
            If provided, scopes retrieval to the specified owner.

        Returns
        -------
        Incident | None
            The Incident model if found and owned, or None if not found/unauthorized.
        """
        stmt = select(Incident).where(Incident.id == incident_id)
        if owner_id is not None:
            stmt = stmt.where(or_(Incident.owner_id == owner_id, Incident.owner_id.is_(None)))
        return self.db.execute(stmt).scalars().first()

    def list_incident_events(
        self,
        incident_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
        owner_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[Event], int] | None:
        """
        Retrieve paginated events associated with a specific incident.
        """
        # Verify parent incident exists and is owned by owner_id
        parent_incident = self.get_incident_by_id(incident_id, owner_id=owner_id)
        if parent_incident is None:
            return None

        stmt = select(Event).where(Event.incident_id == incident_id)

        # Count total events belonging to this incident
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.db.scalar(count_stmt) or 0

        # Deterministic ordering: most recent timestamp first, tie-break by ID
        stmt = stmt.order_by(Event.timestamp.desc(), Event.id.desc())
        stmt = stmt.limit(limit).offset(offset)

        events = self.db.execute(stmt).scalars().all()
        return events, total

        stmt = select(Event).where(Event.incident_id == incident_id)

        # Count total events belonging to this incident
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.db.scalar(count_stmt) or 0

        # Deterministic ordering: most recent timestamp first, tie-break by ID
        stmt = stmt.order_by(Event.timestamp.desc(), Event.id.desc())
        stmt = stmt.limit(limit).offset(offset)

        events = self.db.execute(stmt).scalars().all()
        return events, total


def get_incident_service(db: Session = Depends(get_db)) -> IncidentService:
    """
    FastAPI dependency that provides an IncidentService instance.
    
    Injects the active request-scoped database Session.
    """
    return IncidentService(db=db)
