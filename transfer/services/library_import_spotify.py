"""Spotify playlist import validation and persistence."""

import re
from urllib.parse import urlparse

from django.db import transaction

from ..models import LibraryPlaylist, LibraryTrack
from .common import TransferError
from .library_track_management import append_provider_track


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
    if (
        len(parts) < 2
        or parts[-2] != resource_type
        or not re.fullmatch(r"[A-Za-z0-9]{22}", parts[-1])
    ):
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



def save_spotify_track(profile, track, source_url, *, playlist=None, fallback_track_id=""):
    """Append a Spotify track or create a one-track playlist for it."""
    if playlist is None:
        resource = {"name": f"Spotify — {track.get('name') or 'Track'}"}
        playlist, _count = save_spotify_playlist(
            profile,
            resource,
            [{"item": track}],
            source_url,
        )
        return playlist

    artists = track.get("artists") or []
    artist = ", ".join(
        str(item.get("name") or "")
        for item in artists
        if isinstance(item, dict) and item.get("name")
    ) or "Unknown artist"
    album_payload = track.get("album")
    album = album_payload.get("name") or "" if isinstance(album_payload, dict) else ""
    external_urls = track.get("external_urls")
    external_url = (
        external_urls.get("spotify", source_url)
        if isinstance(external_urls, dict)
        else source_url
    )
    images = album_payload.get("images") or [] if isinstance(album_payload, dict) else []
    cover_url = (
        images[0].get("url", "")
        if images and isinstance(images[0], dict)
        else ""
    )
    append_provider_track(
        playlist,
        title=track.get("name") or "Unknown track",
        artist=artist,
        album=album,
        provider=LibraryPlaylist.Provider.SPOTIFY,
        external_id=track.get("id") or fallback_track_id,
        external_url=external_url,
        duration_ms=track.get("duration_ms"),
        cover_url=cover_url,
    )
    return playlist



def import_spotify_library(profile, client, token, *, limit=30):
    """Import a bounded batch of the user's Spotify playlists."""
    resources = client.my_playlists(token)
    imported = 0
    track_count = 0
    skipped = 0
    for resource in resources[:limit]:
        playlist_id = resource.get("id")
        if not playlist_id:
            continue
        try:
            entries = client.get_playlist_items(token, playlist_id)
            count = len(entries)
            if count:
                external_urls = resource.get("external_urls") or {}
                save_spotify_playlist(
                    profile,
                    resource,
                    entries,
                    external_urls.get("spotify", ""),
                )
                imported += 1
                track_count += count
        except TransferError:
            skipped += 1
    return imported, track_count, skipped



def import_spotify_playlist(profile, client, token, playlist_id, source_url):
    """Fetch and persist one Spotify playlist after URL validation."""
    resource = client.api("playlist_details", token, playlist_id=playlist_id)
    entries = client.get_playlist_items(token, playlist_id)
    return save_spotify_playlist(profile, resource, entries, source_url)
