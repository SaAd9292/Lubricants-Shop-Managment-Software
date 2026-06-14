"""Domain-specific exceptions. Catch these at the controller/UI boundary."""
from __future__ import annotations


class LubriPosError(Exception):
    """Base class for all application errors."""


class AuthError(LubriPosError):
    """Authentication / login failure."""


class PermissionDenied(LubriPosError):
    """Authenticated user lacks the required role for an action."""


class ValidationError(LubriPosError):
    """User input failed validation."""


class NotFoundError(LubriPosError):
    """A requested record does not exist."""


class InsufficientStockError(LubriPosError):
    """A sale would drive product stock below zero."""
