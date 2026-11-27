"""Persistence and provider-payload mapping for library imports."""

import re
from urllib.parse import urlparse

from django.db import transaction

from ..models import LibraryPlaylist, LibraryTrack
from .common import TransferError


def spotify_resource_id(value, resource_type):
    value = (value or "").strip()
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Укажи ссылку на Spotify.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"open.spotify.com", "www.open.spotify.com"}
        or port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Укажи ссылку на Spotify.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[-2] != resource_type or not re.fullmatch(r"[A-Za-z0-9]{22}", parts[-1]):
        raise ValueError("Ссылка Spotify имеет неверный формат.")
    return parts[-1]


def save_spotify_playlist(profile, resource, entries, source_url):
    """Persist valid Spotify track items, preserving provider order."""
    with transaction.atomic():
        playlist = LibraryPlaylist.objects.create(
            profile=profile,
            title=str(resource.get("name") or "Spotify playlist")[:120],
            provider=LibraryPlaylist.Provider.SPOTIFY,
            external_url=source_url,
            description="Импортировано из Spotify",
        )
        rows = []
        for index, entry in enumerate(entries):
            track = entry.get("item") or entry.get("track") or {}
            if track.get("type") not in (None, "track") or not track.get("id"):
                continue
            artists = track.get("artists") or []
            artist = ", ".join(
                str(item.get("name") or "") for item in artists if item.get("name")
            )
            album = (track.get("album") or {}).get("name") or ""
            external_url = (track.get("external_urls") or {}).get("spotify", "")
            rows.append(
                LibraryTrack(
                    playlist=playlist,
                    title=str(track.get("name") or "Unknown track")[:180],
                    artist=artist[:180] or "Unknown artist",
                    album=str(album)[:180],
                    duration_ms=track.get("duration_ms"),
                    external_id=str(track.get("id"))[:200],
                    external_url=str(external_url)[:2048],
                    position=index,
                )
            )
        if not rows:
            raise TransferError("Spotify не вернул доступные композиции этого плейлиста.")
        LibraryTrack.objects.bulk_create(rows)
    return playlist, len(rows)


def validate_soundcloud_permalink(value):
    parsed = urlparse((value or "").strip())
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Укажи публичную HTTPS-ссылку на soundcloud.com.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {
            "soundcloud.com", "www.soundcloud.com", "m.soundcloud.com",
        }
        or port not in (None, 443)
        or not parsed.path
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Укажи публичную HTTPS-ссылку на soundcloud.com.")
    return parsed.geturl()


def save_soundcloud_playlist(profile, resource, tracks, source_url):
    """Persist usable SoundCloud track payloads without empty playlists."""
    with transaction.atomic():
        playlist = LibraryPlaylist.objects.create(
            profile=profile,
            title=str(resource.get("title") or "SoundCloud playlist")[:120],
            provider=LibraryPlaylist.Provider.SOUNDCLOUD,
            external_url=source_url,
            description=f"Импортировано из SoundCloud · {len(tracks)} композиций",
        )
        rows = []
        for index, item in enumerate(tracks):
            if not isinstance(item, dict) or not item.get("id") or not item.get("title"):
                continue
            user = item.get("user")
            if not isinstance(user, dict):
                user = {}
            try:
                raw_duration = item.get("duration")
                if isinstance(raw_duration, bool):
                    raise TypeError("Boolean duration is invalid.")
                parsed_duration = max(0, int(raw_duration or 0))
                duration_ms = (
                    parsed_duration if parsed_duration <= 2_147_483_647 else None
                )
            except (TypeError, ValueError, OverflowError):
                duration_ms = None
            rows.append(
                LibraryTrack(
                    playlist=playlist,
                    title=str(item.get("title") or "Unknown track")[:180],
                    artist=str(
                        item.get("metadata_artist")
                        or user.get("username")
                        or "Unknown artist"
                    )[:180],
                    duration_ms=duration_ms,
                    external_id=str(item.get("id"))[:200],
                    external_url=str(item.get("permalink_url") or "")[:2048],
                    position=index,
                )
            )
        if not rows:
            raise TransferError("SoundCloud не вернул доступные композиции.")
        LibraryTrack.objects.bulk_create(rows)
    return playlist, len(rows)


def save_vk_playlist(profile, title, tracks, source_url):
    """Persist VK playlist metadata and its tracks atomically."""
    if not tracks:
        raise TransferError("VK не вернул композиции для импорта.")
    with transaction.atomic():
        playlist = LibraryPlaylist.objects.create(
            profile=profile,
            title=title[:120] or "Импорт из VK",
            provider=LibraryPlaylist.Provider.VK,
            external_url=source_url,
            description=f"Импортировано из VK · {len(tracks)} композиций",
        )
        LibraryTrack.objects.bulk_create(
            [
                LibraryTrack(
                    playlist=playlist,
                    title=track.title[:180],
                    artist=track.artist[:180],
                    duration_ms=max(track.duration, 0) * 1000,
                    cover_url=track.cover_url,
                    external_id=track.audio_id or f"{track.owner_id}_{track.track_id}",
                    external_url=f"https://vk.ru/audio{track.owner_id}_{track.track_id}",
                    source_provider=LibraryPlaylist.Provider.VK,
                    position=index,
                )
                for index, track in enumerate(tracks)
            ]
        )
    return playlist, len(tracks)


def save_vk_track(profile, track, source_url):
    with transaction.atomic():
        playlist = LibraryPlaylist.objects.create(
            profile=profile,
            title=f"VK — {track.artist} — {track.title}"[:120],
            provider=LibraryPlaylist.Provider.VK,
            external_url=source_url,
            description="Импортирована отдельная аудиозапись VK",
        )
        LibraryTrack.objects.create(
            playlist=playlist,
            title=track.title[:180],
            artist=track.artist[:180],
            duration_ms=max(0, track.duration) * 1000,
            cover_url=track.cover_url,
            external_id=track.audio_id or f"{track.owner_id}_{track.track_id}",
            external_url=source_url,
            source_provider=LibraryPlaylist.Provider.VK,
            position=0,
        )
    return playlist


def refresh_vk_track_metadata(playlist, vk_tracks):
    indexed = {f"{item.owner_id}_{item.track_id}": item for item in vk_tracks}
    updated = 0
    for track in playlist.tracks.all():
        base_id = "_".join(track.external_id.split("_")[:2])
        source = indexed.get(base_id)
        if not source:
            continue
        changed = []
        if source.cover_url and track.cover_url != source.cover_url:
            track.cover_url = source.cover_url
            changed.append("cover_url")
        if source.audio_id and track.external_id != source.audio_id:
            track.external_id = source.audio_id
            changed.append("external_id")
        if track.source_provider != LibraryPlaylist.Provider.VK:
            track.source_provider = LibraryPlaylist.Provider.VK
            changed.append("source_provider")
        if changed:
            track.save(update_fields=changed)
            updated += 1
    return updated
