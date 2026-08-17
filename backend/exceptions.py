"""
Rio CRM Exception Hierarchy

Structured error taxonomy for proper error handling and observability.
"""


class RioError(Exception):
    """Base exception for all Rio CRM errors."""
    pass


# External Service Errors
class ExternalServiceError(RioError):
    """Base for external service failures (Twilio, Deepgram, etc.)."""
    pass


class TelephonyError(ExternalServiceError):
    """Twilio, EnableX, Exotel failures."""
    pass


class AIServiceError(ExternalServiceError):
    """LLM, STT, TTS provider failures."""
    pass


class EnrichmentServiceError(ExternalServiceError):
    """Apollo, Lusha, ZoomInfo failures."""
    pass


# Data & Database Errors
class DataError(RioError):
    """Base for data-related errors."""
    pass


class DataIntegrityError(DataError):
    """Database constraint violations, invalid state."""
    pass


class TenantIsolationError(DataError):
    """RLS policy violation or cross-tenant access attempt."""
    pass


# Business Logic Errors
class BusinessLogicError(RioError):
    """Base for business rule violations."""
    pass


class QuotaExceededError(BusinessLogicError):
    """Usage quota exceeded for company tier."""
    pass


class InvalidStateTransitionError(BusinessLogicError):
    """Invalid ISM stage transition or workflow state change."""
    pass


# Authentication & Authorization
class AuthError(RioError):
    """Base for auth-related errors."""
    pass


class AuthenticationError(AuthError):
    """Invalid credentials, expired token."""
    pass


class AuthorizationError(AuthError):
    """Insufficient permissions."""
    pass


class MFARequiredError(AuthError):
    """MFA verification required."""
    pass


# Observability & Infrastructure
class ObservabilityError(RioError):
    """Non-critical observability failures (metrics, tracing)."""
    pass


class ConfigurationError(RioError):
    """Missing or invalid configuration."""
    pass
