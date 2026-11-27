"""Configured OAuth client factories for external music providers."""
from django.conf import settings

from ..services import SoundCloudClient, SpotifyClient, TransferError


def spotify_client():
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
        raise TransferError("Spotify OAuth не настроен на сервере.")
    return SpotifyClient(settings.SPOTIFY_CLIENT_ID, settings.SPOTIFY_CLIENT_SECRET, settings.SPOTIFY_REDIRECT_URI)


def soundcloud_client():
    if not settings.SOUNDCLOUD_CLIENT_ID or not settings.SOUNDCLOUD_CLIENT_SECRET:
        raise TransferError("SoundCloud OAuth не настроен на сервере.")
    return SoundCloudClient(settings.SOUNDCLOUD_CLIENT_ID, settings.SOUNDCLOUD_CLIENT_SECRET, settings.SOUNDCLOUD_REDIRECT_URI)
