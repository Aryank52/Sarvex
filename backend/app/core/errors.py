"""Typed application errors mapped to consistent HTTP responses."""
from __future__ import annotations


class SarvexError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFoundError(SarvexError):
    status_code = 404
    code = "not_found"


class ValidationError(SarvexError):
    status_code = 422
    code = "validation_error"


class ConflictError(SarvexError):
    status_code = 409
    code = "conflict"


class UnauthorizedError(SarvexError):
    status_code = 401
    code = "unauthorized"


class RateLimitError(SarvexError):
    status_code = 429
    code = "rate_limited"


class CapabilityUnavailableError(SarvexError):
    status_code = 501
    code = "capability_unavailable"


class ProcessingError(SarvexError):
    status_code = 500
    code = "processing_error"


class DemoModeError(SarvexError):
    status_code = 409
    code = "demo_mode_required"
