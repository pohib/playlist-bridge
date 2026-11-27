"""Backward-compatible facade for the versioned HTTP API.

Concrete endpoints, serialization and shared response helpers live in
transfer.api. Keep these re-exports so existing imports and URL wiring
continue to work while the API package evolves independently.
"""
from .api import (
    api_create_transfer,
    api_docs,
    api_error,
    api_not_found,
    api_openapi,
    api_status,
    api_transfer_detail,
    api_transfer_report,
    serialize_job,
)

__all__ = [
    "api_create_transfer",
    "api_docs",
    "api_error",
    "api_not_found",
    "api_openapi",
    "api_status",
    "api_transfer_detail",
    "api_transfer_report",
    "serialize_job",
]
