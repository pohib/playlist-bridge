"""Session binding and connected-provider queries for OAuth workflows."""

from django.db import transaction

from ..models import LibraryProfile, OAuthCredential, TransferJob
from .credential_service import get_session_fingerprint


def rotate_session_binding(request):
    """Move session-owned records to the fingerprint of the rotated session."""
    old_fingerprint = get_session_fingerprint(request)
    request.session.cycle_key()
    new_fingerprint = get_session_fingerprint(request)

    with transaction.atomic():
        OAuthCredential.objects.filter(session_fingerprint=old_fingerprint).update(
            session_fingerprint=new_fingerprint
        )
        TransferJob.objects.filter(session_fingerprint=old_fingerprint).update(
            session_fingerprint=new_fingerprint
        )
        LibraryProfile.objects.filter(session_fingerprint=old_fingerprint).update(
            session_fingerprint=new_fingerprint
        )

    return new_fingerprint


def connected_providers(request):
    """Return the legacy Spotify/VK/SoundCloud connection flags for a session."""
    fingerprint = get_session_fingerprint(request)
    providers = set(
        OAuthCredential.objects.filter(session_fingerprint=fingerprint).values_list(
            "provider", flat=True
        )
    )
    return (
        OAuthCredential.Provider.SPOTIFY in providers,
        False,
        OAuthCredential.Provider.SOUNDCLOUD in providers,
    )
