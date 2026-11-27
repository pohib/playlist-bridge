"""Track CRUD domain operations."""

from django.db import transaction

from ..models import LibraryTrack
from .library_management_errors import LibraryManagementError
from .library_playlist_management import _safe_optional_url


def add_track(
    playlist, *, title, artist, album="", external_id="", external_url="",
    duration_seconds="",
):
    title = (title or "").strip()
    artist = (artist or "").strip()
    album = (album or "").strip()
    external_id = (external_id or "").strip()
    try:
        external_url = _safe_optional_url(external_url)
        duration_ms = int(float(duration_seconds) * 1000) if duration_seconds else None
    except (LibraryManagementError, ValueError, OverflowError) as exc:
        raise LibraryManagementError(
            "Проверь ссылку и длительность композиции."
        ) from exc
    if (
        not title or not artist or len(title) > 180
        or len(artist) > 180 or len(album) > 180
    ):
        raise LibraryManagementError(
            "Название и исполнитель обязательны (до 180 символов)."
        )
    if duration_ms is not None and not 0 < duration_ms <= 86_400_000:
        raise LibraryManagementError(
            "Длительность должна быть от 1 секунды до 24 часов."
        )
    if len(external_id) > 200:
        raise LibraryManagementError("Внешний ID слишком длинный.")
    with transaction.atomic():
        track = LibraryTrack.objects.create(
            playlist=playlist, title=title, artist=artist, album=album,
            duration_ms=duration_ms, external_id=external_id,
            external_url=external_url, position=playlist.tracks.count(),
        )
        playlist.save(update_fields=["updated_at"])
    return track


def delete_track(track):
    track.delete()
