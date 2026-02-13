"""Custom exceptions for the JobOS application."""


class AIServiceError(Exception):
    """Raised when the AI service (Claude API) fails with a non-retryable error."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause
