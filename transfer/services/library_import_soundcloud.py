"""SoundCloud playlist import validation and persistence."""

from urllib.parse import urlparse

from django.db import transaction

from ..models import LibraryPlaylist, LibraryTrack
from .common import TransferError
from .library_track_management import append_provider_track


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



def save_soundcloud_track(profile, resource, source_url, *, playlist=None):
    """Append a SoundCloud track or create a one-track playlist for it."""
    if playlist is None:
        playlist, _count = save_soundcloud_playlist(
            profile,
            {"title": f"SoundCloud — {resource.get('title') or 'Track'}"},
            [resource],
            source_url,
        )
        return playlist

    user = resource.get("user")
    if not isinstance(user, dict):
        user = {}
    append_provider_track(
        playlist,
        title=resource.get("title") or "Unknown track",
        artist=(
            resource.get("metadata_artist")
            or user.get("username")
            or "Unknown artist"
        ),
        provider=LibraryPlaylist.Provider.SOUNDCLOUD,
        external_id=resource.get("id", ""),
        external_url=resource.get("permalink_url") or source_url,
        duration_ms=resource.get("duration"),
        cover_url=resource.get("artwork_url") or "",
    )
    return playlist



def import_soundcloud_library(profile, client, token, *, limit=30):
    """Import a bounded batch of the user's SoundCloud playlists."""
    resources = client.my_playlists(token)
    imported = 0
    track_count = 0
    for resource in resources[:limit]:
        resource_id = resource.get("id")
        if not resource_id:
            continue
        tracks = client.playlist_tracks(token, resource_id)
        source_url = resource.get("permalink_url") or ""
        if source_url:
            save_soundcloud_playlist(profile, resource, tracks, source_url)
            imported += 1
            track_count += len(tracks)
    return imported, track_count
