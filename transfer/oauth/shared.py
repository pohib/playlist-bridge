"""Shared helpers used by provider OAuth flows."""

from cryptography.fernet import Fernet
from django.conf import settings

from ..services.oauth_session_service import (
    connected_providers as _connected_providers,
    rotate_session_binding as _rotate_session_binding,
)


def encryption_key_is_valid():
    try:
        Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())
        return True
    except (ValueError, AttributeError):
        return False


def rotate_session_binding(request):
    """Compatibility wrapper for the OAuth session service."""
    return _rotate_session_binding(request)


def connected_providers(request):
    """Compatibility wrapper for the OAuth session service."""
    return _connected_providers(request)


def provider_redirect(request):
    return "connections" if request.user.is_authenticated else "home"
