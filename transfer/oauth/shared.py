"""Shared helpers used by provider OAuth flows."""

from cryptography.fernet import Fernet
from django.conf import settings

from ..models import LibraryProfile, OAuthCredential, TransferJob
from ..services.credential_service import get_session_fingerprint


def encryption_key_is_valid():
    try:
        Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())
        return True
    except (ValueError, AttributeError):
        return False


def rotate_session_binding(request):
    old_fingerprint = get_session_fingerprint(request)
    request.session.cycle_key()
    new_fingerprint = get_session_fingerprint(request)
    OAuthCredential.objects.filter(session_fingerprint=old_fingerprint).update(
        session_fingerprint=new_fingerprint
    )
    TransferJob.objects.filter(session_fingerprint=old_fingerprint).update(
        session_fingerprint=new_fingerprint
    )
    LibraryProfile.objects.filter(session_fingerprint=old_fingerprint).update(
        session_fingerprint=new_fingerprint
    )


def connected_providers(request):
    fingerprint = get_session_fingerprint(request)
    providers = set(
        OAuthCredential.objects.filter(session_fingerprint=fingerprint).values_list(
            "provider", flat=True
        )
    )
    return "spotify" in providers, False, "soundcloud" in providers


def provider_redirect(request):
    return "connections" if request.user.is_authenticated else "home"
