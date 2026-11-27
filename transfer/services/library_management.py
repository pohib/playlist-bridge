"""Domain operations for user-owned library mutations.

The service layer accepts already-resolved domain objects and owns validation,
transactions and persistence. HTTP messages, redirects and object-not-found
responses remain in the view adapters.
"""

import re
import unicodedata
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction

from ..models import LibraryPlaylist, LibraryTrack


class LibraryManagementError(ValueError):
    """A user-correctable library mutation error."""


def _safe_optional_url(value):
    value = (value or "").strip()
    if value:
        try:
            URLValidator(schemes=["http", "https"])(value)
        except ValidationError as exc:
            raise LibraryManagementError(
                "Ссылка должна быть корректным HTTP(S)-адресом."
            ) from exc
    return value


def create_playlist(profile, *, title, provider, description="", external_url=""):
    title = (title or "").strip()
    description = (description or "").strip()
    external_url = _safe_optional_url(external_url)
    if not title or len(title) > 120 or len(description) > 240:
        raise LibraryManagementError("Укажи название плейлиста (до 120 символов).")
    if provider not in LibraryPlaylist.Provider.values:
        raise LibraryManagementError("Неизвестный музыкальный сервис.")
    return LibraryPlaylist.objects.create(
        profile=profile,
        title=title,
        provider=provider,
        description=description,
        external_url=external_url,
    )


def add_track(
    playlist,
    *,
    title,
    artist,
    album="",
    external_id="",
    external_url="",
    duration_seconds="",
):
    title = (title or "").strip()
    artist = (artist or "").strip()
    album = (album or "").strip()
    external_id = (external_id or "").strip()
    try:
        external_url = _safe_optional_url(external_url)
        duration_ms = (
            int(float(duration_seconds) * 1000) if duration_seconds else None
        )
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
            playlist=playlist,
            title=title,
            artist=artist,
            album=album,
            duration_ms=duration_ms,
            external_id=external_id,
            external_url=external_url,
            position=playlist.tracks.count(),
        )
        playlist.save(update_fields=["updated_at"])
    return track


def delete_track(track):
    track.delete()


def delete_playlist(playlist):
    playlist.delete()


def _normalized_track_key(artist, title):
    value = unicodedata.normalize(
        "NFKD", f"{artist} {title}".casefold().replace("ё", "е")
    )
    return re.sub(r"[^a-z0-9а-я]+", " ", value).strip()


def merge_playlists(profile, playlist_ids, title):
    playlist_ids = list(dict.fromkeys(str(item) for item in playlist_ids))
    title = (title or "").strip()
    if len(playlist_ids) < 2:
        raise LibraryManagementError(
            "Выбери минимум два плейлиста для объединения."
        )
    if len(playlist_ids) > 30:
        raise LibraryManagementError(
            "За один раз можно объединить не более 30 плейлистов."
        )
    if not title or len(title) > 120:
        raise LibraryManagementError(
            "Укажи название новой коллекции (до 120 символов)."
        )

    owned = {
        str(item.pk): item
        for item in LibraryPlaylist.objects.filter(
            profile=profile, pk__in=playlist_ids
        )
    }
    if len(owned) != len(playlist_ids):
        raise LibraryManagementError(
            "Один из выбранных плейлистов не найден."
        )

    ordered_sources = [owned[item_id] for item_id in playlist_ids]
    with transaction.atomic():
        merged = LibraryPlaylist.objects.create(
            profile=profile,
            title=title,
            provider=LibraryPlaylist.Provider.MANUAL,
            description=f"Объединено из {len(ordered_sources)} плейлистов",
        )
        seen = set()
        merged_rows = []
        for source in ordered_sources:
            for track in source.tracks.all().order_by("position", "created_at"):
                key = _normalized_track_key(track.artist, track.title)
                if key in seen:
                    continue
                seen.add(key)
                merged_rows.append(
                    LibraryTrack(
                        playlist=merged,
                        title=track.title,
                        artist=track.artist,
                        album=track.album,
                        duration_ms=track.duration_ms,
                        cover_url=track.cover_url,
                        external_id=track.external_id,
                        external_url=track.external_url,
                        source_provider=(
                            track.source_provider or source.provider
                        ),
                        audio_file=track.audio_file,
                        position=len(merged_rows),
                    )
                )
        if not merged_rows:
            raise LibraryManagementError(
                "В выбранных плейлистах нет композиций для объединения."
            )
        LibraryTrack.objects.bulk_create(merged_rows)
    return merged, len(merged_rows)


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
            profile=profile,
            title="Мои аудиофайлы",
            defaults={
                "provider": LibraryPlaylist.Provider.MANUAL,
                "description": (
                    "Личные аудиофайлы, загруженные в Playlist Bridge"
                ),
            },
        )
        track = LibraryTrack.objects.create(
            playlist=playlist,
            title=title,
            artist=artist,
            source_provider=LibraryPlaylist.Provider.MANUAL,
            audio_file=uploaded,
            position=playlist.tracks.count(),
        )
        playlist.save(update_fields=["updated_at"])
    return playlist, track


def update_profile(profile, display_name):
    display_name = (display_name or "").strip()
    if not display_name or len(display_name) > 60:
        raise LibraryManagementError(
            "Имя профиля должно содержать от 1 до 60 символов."
        )
    profile.display_name = display_name
    profile.save(update_fields=["display_name", "updated_at"])
    return profile
