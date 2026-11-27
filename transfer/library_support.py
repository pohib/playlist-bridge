"""Shared helpers for library-facing views."""

from urllib.parse import urlparse

from django.conf import settings

from .services.credential_service import get_access_token, get_session_fingerprint
from .models import LibraryProfile
from .services import SoundCloudClient, SpotifyClient


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


def _safe_candidate_url(value, provider):
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    try:
        parsed = urlparse(value.strip())
        port = parsed.port
    except ValueError:
        return ""
    allowed_hosts = {
        "spotify": {"open.spotify.com", "www.open.spotify.com"},
        "soundcloud": {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"},
    }
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts.get(provider, set())
        or port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        return ""
    return parsed.geturl()


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
