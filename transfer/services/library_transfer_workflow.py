"""Application workflow for starting a cross-provider playlist transfer."""

from django.conf import settings

from ..models import LibraryPlaylist
from . import SoundCloudClient, SpotifyClient, TransferError
from .credential_service import get_access_token
from .library_transfer_creation import create_library_transfer


def create_library_transfer_workflow(
    *,
    playlist,
    target_provider,
    fingerprint,
    safe_candidate_url,
):
    """Validate a transfer request, authorize its provider and create its review."""
    if target_provider not in {
        LibraryPlaylist.Provider.SPOTIFY,
        LibraryPlaylist.Provider.SOUNDCLOUD,
    }:
        raise TransferError("Выбери поддерживаемый целевой сервис.")

    tracks = list(playlist.tracks.all())
    if not tracks:
        raise TransferError("В плейлисте нет композиций для переноса.")
    if len(tracks) > 100:
        raise TransferError("Пока можно переносить не более 100 композиций за один запуск.")

    if target_provider == LibraryPlaylist.Provider.SPOTIFY:
        client = SpotifyClient(
            settings.SPOTIFY_CLIENT_ID,
            settings.SPOTIFY_CLIENT_SECRET,
            settings.SPOTIFY_REDIRECT_URI,
        )
    else:
        client = SoundCloudClient(
            settings.SOUNDCLOUD_CLIENT_ID,
            settings.SOUNDCLOUD_CLIENT_SECRET,
            settings.SOUNDCLOUD_REDIRECT_URI,
        )

    token, _ = get_access_token(fingerprint, target_provider, client)
    return create_library_transfer(
        playlist=playlist,
        target_provider=target_provider,
        tracks=tracks,
        client=client,
        token=token,
        safe_candidate_url=safe_candidate_url,
    )
