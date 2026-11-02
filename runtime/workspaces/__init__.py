"""Shared, device-independent workspace discovery and field primitives."""

from .catalog import discover_modules
from .fields import normalize_fields

__all__ = ["discover_modules", "normalize_fields"]
