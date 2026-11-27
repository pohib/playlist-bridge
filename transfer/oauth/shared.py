"""Shared helpers used by provider OAuth flows."""

from cryptography.fernet import Fernet
from django.conf import settings

from ..services import oauth_session_service


def encryption_key_is_valid():
    try:
        Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())
        return True
    except (ValueError, AttributeError):
        return False


def rotate_session_binding(request):
    """Compatibility wrapper for the OAuth session service."""
    return oauth_session_service.rotate_session_binding(request)


def connected_providers(request):
    """Compatibility wrapper for the OAuth session service."""
    return oauth_session_service.connected_providers(request)


def provider_redirect(request):
    return "connections" if request.user.is_authenticated else "home"
