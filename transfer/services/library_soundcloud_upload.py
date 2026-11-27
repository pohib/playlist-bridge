"""SoundCloud audio upload and local library persistence."""

from pathlib import Path

from django.db import transaction

from ..models import LibraryPlaylist, LibraryTrack
from .audio_file_validation import (
    SOUNDCLOUD_AUDIO_EXTENSIONS,
    has_audio_file_signature,
)
from .common import TransferError


_MAX_UPLOAD_SIZE = 100 * 1024 * 1024


def _validate_upload(uploaded, title, artist):
    if not uploaded or not title or not artist or len(title) > 100 or len(artist) > 100:
        raise TransferError("Выбери аудиофайл и укажи название и исполнителя.")

    extension = Path(uploaded.name).suffix.lower()
    if extension not in SOUNDCLOUD_AUDIO_EXTENSIONS or uploaded.size > _MAX_UPLOAD_SIZE:
        raise TransferError(
            "Поддерживаются аудиофайлы до 100 МБ в форматах MP3, WAV, FLAC, "
            "AIFF, OGG, AAC, AMR, WMA и MP2."
        )
    if not has_audio_file_signature(uploaded, extension):
        raise TransferError("Содержимое файла не соответствует заявленному аудиоформату.")


def upload_soundcloud_track(
    *,
    profile,
    uploaded,
    title,
    artist,
    description,
    soundcloud_access,
):
    """Validate, upload remotely, then atomically persist the local mirror.

    The provider request intentionally happens before the database transaction.
    """
    _validate_upload(uploaded, title, artist)
    client, token = soundcloud_access()
    result = client.upload_track(token, uploaded, title, artist, description)
    if not isinstance(result, dict):
        raise TransferError("SoundCloud вернул некорректный ответ после загрузки.")
    external_id = str(result.get("id") or "").strip()
    if not external_id:
        raise TransferError("SoundCloud не вернул идентификатор загруженного трека.")

    permalink = str(result.get("permalink_url") or "")
    raw_duration = result.get("duration") or 0
    try:
        duration_ms = max(0, int(raw_duration))
    except (TypeError, ValueError, OverflowError):
        duration_ms = 0

    with transaction.atomic():
        playlist = LibraryPlaylist.objects.create(
            profile=profile,
            title=title[:120],
            provider=LibraryPlaylist.Provider.SOUNDCLOUD,
            external_url=permalink,
            description="Загружено в SoundCloud",
        )
        LibraryTrack.objects.create(
            playlist=playlist,
            title=title[:180],
            artist=artist[:180],
            duration_ms=duration_ms,
            external_id=external_id,
            external_url=permalink,
            position=0,
        )
    return playlist
