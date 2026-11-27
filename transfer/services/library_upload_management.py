"""Local audio upload validation and persistence."""

from pathlib import Path

from django.db import transaction

from ..models import LibraryPlaylist, LibraryTrack
from .library_management_errors import LibraryManagementError


def _audio_signature_matches(suffix, header):
    signatures = {
        ".wav": header.startswith(b"RIFF") and header[8:12] == b"WAVE",
        ".ogg": header.startswith(b"OggS"),
        ".flac": header.startswith(b"fLaC"),
        ".m4a": header[4:8] == b"ftyp",
        ".mp3": header.startswith(b"ID3") or (
            len(header) > 1 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
        ),
    }
    return signatures.get(suffix, False)


def upload_local_track(profile, *, title, artist, uploaded):
    title = (title or "").strip()
    artist = (artist or "").strip()
    allowed = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
    if (
        not title or len(title) > 180 or not artist
        or len(artist) > 180 or not uploaded
    ):
        raise LibraryManagementError(
            "Укажи название, исполнителя и аудиофайл."
        )
    suffix = Path(uploaded.name).suffix.lower()
    if suffix not in allowed or uploaded.size > 100 * 1024 * 1024:
        raise LibraryManagementError(
            "Поддерживаются MP3, WAV, OGG, FLAC и M4A размером до 100 МБ."
        )
    header = uploaded.read(16)
    uploaded.seek(0)
    if not _audio_signature_matches(suffix, header):
        raise LibraryManagementError(
            "Содержимое файла не соответствует заявленному аудиоформату."
        )
    with transaction.atomic():
        playlist, _ = LibraryPlaylist.objects.get_or_create(
            profile=profile, title="Мои аудиофайлы",
            defaults={
                "provider": LibraryPlaylist.Provider.MANUAL,
                "description": "Личные аудиофайлы, загруженные в Playlist Bridge",
            },
        )
        track = LibraryTrack.objects.create(
            playlist=playlist, title=title, artist=artist,
            source_provider=LibraryPlaylist.Provider.MANUAL,
            audio_file=uploaded, position=playlist.tracks.count(),
        )
        playlist.save(update_fields=["updated_at"])
    return playlist, track
