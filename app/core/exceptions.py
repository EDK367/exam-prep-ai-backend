"""
Custom exception hierarchy for Exam Prep AI.
All domain exceptions inherit from AppError for centralized handling.
"""
from typing import Any


class AppError(Exception):
    """Base application error."""
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str = "An unexpected error occurred", details: Any = None):
        self.message = message
        self.details = details
        super().__init__(self.message)


# ── Auth / Access ────────────────────────────────────────────────────────────
class AuthenticationError(AppError):
    status_code = 401
    error_code = "AUTHENTICATION_ERROR"

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message)


class AuthorizationError(AppError):
    status_code = 403
    error_code = "AUTHORIZATION_ERROR"

    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message)


# ── Resource ─────────────────────────────────────────────────────────────────
class NotFoundError(AppError):
    status_code = 404
    error_code = "NOT_FOUND"

    def __init__(self, resource: str = "Resource", identifier: str = ""):
        message = f"{resource} not found"
        if identifier:
            message = f"{resource} '{identifier}' not found"
        super().__init__(message)


class ConflictError(AppError):
    status_code = 409
    error_code = "CONFLICT"

    def __init__(self, message: str = "Resource conflict"):
        super().__init__(message)


# ── Validation ───────────────────────────────────────────────────────────────
class ValidationError(AppError):
    status_code = 422
    error_code = "VALIDATION_ERROR"

    def __init__(self, message: str = "Validation failed", details: Any = None):
        super().__init__(message, details)


class FileValidationError(ValidationError):
    error_code = "FILE_VALIDATION_ERROR"


# ── Subscription / Limits ────────────────────────────────────────────────────
class SubscriptionError(AppError):
    status_code = 403
    error_code = "SUBSCRIPTION_ERROR"

    def __init__(self, message: str = "Subscription required"):
        super().__init__(message)


class PlanLimitExceededError(SubscriptionError):
    error_code = "PLAN_LIMIT_EXCEEDED"

    def __init__(self, limit_type: str, current: int, maximum: int):
        message = f"Plan limit exceeded for {limit_type}: {current}/{maximum}"
        super().__init__(message)


class SubscriptionExpiredError(SubscriptionError):
    error_code = "SUBSCRIPTION_EXPIRED"

    def __init__(self):
        super().__init__("Your subscription has expired")


class BudgetExceededError(SubscriptionError):
    error_code = "BUDGET_EXCEEDED"

    def __init__(self, message: str = "Monthly AI budget exceeded"):
        super().__init__(message)


# ── Document Processing ─────────────────────────────────────────────────────
class DocumentProcessingError(AppError):
    status_code = 500
    error_code = "DOCUMENT_PROCESSING_ERROR"

    def __init__(self, message: str = "Document processing failed", details: Any = None):
        super().__init__(message, details)


class PDFExtractionError(DocumentProcessingError):
    error_code = "PDF_EXTRACTION_ERROR"


class ChunkingError(DocumentProcessingError):
    error_code = "CHUNKING_ERROR"


# ── AI Service ───────────────────────────────────────────────────────────────
class AIServiceError(AppError):
    status_code = 502
    error_code = "AI_SERVICE_ERROR"

    def __init__(self, message: str = "AI service error", details: Any = None):
        super().__init__(message, details)


class AITimeoutError(AIServiceError):
    error_code = "AI_TIMEOUT"

    def __init__(self):
        super().__init__("AI service request timed out")


class AIRateLimitError(AIServiceError):
    status_code = 429
    error_code = "AI_RATE_LIMITED"

    def __init__(self, retry_after: int | None = None, is_daily_limit: bool = False):
        self.is_daily_limit = is_daily_limit
        message = "AI service rate limited"
        if is_daily_limit:
            message = "AI service daily free quota limit reached"
        elif retry_after:
            message += f", retry after {retry_after}s"
        super().__init__(message)


class AIResponseParsingError(AIServiceError):
    error_code = "AI_RESPONSE_PARSING_ERROR"

    def __init__(self, message: str = "Failed to parse AI response"):
        super().__init__(message)


# ── Rate Limiting ────────────────────────────────────────────────────────────
class RateLimitError(AppError):
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, message: str = "Too many requests"):
        super().__init__(message)
