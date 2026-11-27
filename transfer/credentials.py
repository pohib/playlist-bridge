"""Backward-compatible exports for OAuth credential operations.

New application code should import from transfer.services.credential_service.
"""
from .services.credential_service import (
    decrypt_payload,
    delete_credential,
    encrypt_payload,
    get_access_token,
    get_session_fingerprint,
    load_payload,
    store_credential,
)

__all__ = [
    "decrypt_payload", "delete_credential", "encrypt_payload",
    "get_access_token", "get_session_fingerprint", "load_payload",
    "store_credential",
]
