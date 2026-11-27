"""Request-scoped library profile and provider credential helpers."""

from django.conf import settings

from ..models import LibraryProfile
from .credential_service import get_access_token, get_session_fingerprint
from .soundcloud_client import SoundCloudClient
from .spotify_client import SpotifyClient


def get_request_profile(request):
    """Return the library profile bound to the current user or anonymous session."""
    fingerprint = get_session_fingerprint(request)
    if getattr(request, "user", None) is not None and request.user.is_authenticated:
        profile = LibraryProfile.objects.filter(session_fingerprint=fingerprint).first()
        if profile:
            if profile.user_id != request.user.pk:
                profile.user = request.user
                profile.save(update_fields=["user"])
            return profile
        profile, _ = LibraryProfile.objects.get_or_create(
            user=request.user,
            defaults={"session_fingerprint": fingerprint},
        )
        return profile
    profile, _ = LibraryProfile.objects.get_or_create(session_fingerprint=fingerprint)
    return profile


def get_soundcloud_access(request):
    """Create the SoundCloud client and retrieve the current session token."""
    client = SoundCloudClient(
        settings.SOUNDCLOUD_CLIENT_ID,
        settings.SOUNDCLOUD_CLIENT_SECRET,
        settings.SOUNDCLOUD_REDIRECT_URI,
    )
    token, _ = get_access_token(get_session_fingerprint(request), "soundcloud", client)
    return client, token


def get_spotify_access(request):
    """Create the Spotify client and retrieve the current session token."""
    client = SpotifyClient(
        settings.SPOTIFY_CLIENT_ID,
        settings.SPOTIFY_CLIENT_SECRET,
        settings.SPOTIFY_REDIRECT_URI,
    )
    token, _ = get_access_token(get_session_fingerprint(request), "spotify", client)
    return client, token
