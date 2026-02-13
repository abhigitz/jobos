"""Custom exceptions for the JobOS application."""
from typing import Optional


class AIServiceError(Exception):
    """Raised when the AI service (Claude API) fails with a non-retryable error."""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.cause = cause
