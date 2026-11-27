"""Playlist creation and merge domain operations."""

import re
import unicodedata

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction

from ..models import LibraryPlaylist, LibraryTrack
from .library_management_errors import LibraryManagementError


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
        for item in LibraryPlaylist.objects.filter(profile=profile, pk__in=playlist_ids)
    }
    if len(owned) != len(playlist_ids):
        raise LibraryManagementError("Один из выбранных плейлистов не найден.")
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
                        playlist=merged, title=track.title, artist=track.artist,
                        album=track.album, duration_ms=track.duration_ms,
                        cover_url=track.cover_url, external_id=track.external_id,
                        external_url=track.external_url,
                        source_provider=track.source_provider or source.provider,
                        audio_file=track.audio_file, position=len(merged_rows),
                    )
                )
        if not merged_rows:
            raise LibraryManagementError(
                "В выбранных плейлистах нет композиций для объединения."
            )
        LibraryTrack.objects.bulk_create(merged_rows)
    return merged, len(merged_rows)
