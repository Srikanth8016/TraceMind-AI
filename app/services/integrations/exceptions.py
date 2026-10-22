"""
app/services/integrations/exceptions.py — Domain exceptions for alert integrations & notifications.

Milestone 19: External Alert Integrations & Notifications.
"""


class IntegrationError(Exception):
    """Base exception for all external integration errors."""
    pass


class WebhookAuthenticationError(IntegrationError):
    """Raised when webhook signature or authentication token is missing or invalid (HTTP 401)."""
    pass


class WebhookReplayError(IntegrationError):
    """Raised when webhook timestamp is outside allowed clock drift window (HTTP 400)."""
    pass


class WebhookPayloadValidationError(IntegrationError):
    """Raised when incoming webhook payload does not conform to required structure (HTTP 422)."""
    pass


class WebhookDisabledError(IntegrationError):
    """Raised when an incoming webhook endpoint is administratively disabled (HTTP 503)."""
    pass


class SlackNotificationError(IntegrationError):
    """Raised when outbound Slack notification delivery fails."""
    pass
