"""Shared helpers for library-facing views."""

from django.conf import settings

from .models import LibraryProfile
from .services import SoundCloudClient, SpotifyClient
from .services.credential_service import get_access_token, get_session_fingerprint
from .services.library_source_links import (
    safe_provider_candidate_url as _safe_candidate_url,
)


def _profile(request):
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



def _soundcloud_access(request):
    client = SoundCloudClient(
        settings.SOUNDCLOUD_CLIENT_ID,
        settings.SOUNDCLOUD_CLIENT_SECRET,
        settings.SOUNDCLOUD_REDIRECT_URI,
    )
    token, _ = get_access_token(get_session_fingerprint(request), "soundcloud", client)
    return client, token


def _spotify_access(request):
    client = SpotifyClient(
        settings.SPOTIFY_CLIENT_ID,
        settings.SPOTIFY_CLIENT_SECRET,
        settings.SPOTIFY_REDIRECT_URI,
    )
    token, _ = get_access_token(get_session_fingerprint(request), "spotify", client)
    return client, token
