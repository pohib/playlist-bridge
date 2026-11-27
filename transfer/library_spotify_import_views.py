"""Spotify playlist, track, and library import endpoints."""

import re
from urllib.parse import urlparse

from django.contrib import messages
from django.views.decorators.http import require_POST

from .library_support import _profile, _spotify_access
from .models import LibraryPlaylist, LibraryTrack
from .services import TransferError

def _spotify_resource_id(value, resource_type):
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


def _save_spotify_playlist(profile, resource, entries, source_url):
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
        artist = ", ".join(str(item.get("name") or "") for item in artists if item.get("name"))
        album = (track.get("album") or {}).get("name") or ""
        external_url = (track.get("external_urls") or {}).get("spotify", "")
        rows.append(LibraryTrack(
            playlist=playlist,
            title=str(track.get("name") or "Unknown track")[:180],
            artist=artist[:180] or "Unknown artist",
            album=str(album)[:180],
            duration_ms=track.get("duration_ms"),
            external_id=str(track.get("id"))[:200],
            external_url=str(external_url)[:2048],
            position=index,
        ))
    if not rows:
        playlist.delete()
        raise TransferError("Spotify не вернул доступные композиции этого плейлиста.")
    LibraryTrack.objects.bulk_create(rows)
    return playlist, len(rows)


@require_POST
def import_spotify_playlist(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        playlist_id = _spotify_resource_id(source_url, "playlist")
        client, token = _spotify_access(request)
        resource = client.api("playlist_details", token, playlist_id=playlist_id)
        entries = client.get_playlist_items(token, playlist_id)
        playlist, count = _save_spotify_playlist(_profile(request), resource, entries, source_url)
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Импортирован Spotify-плейлист «{playlist.title}»: {count} композиций.")
    return redirect("library")


@require_POST
def import_spotify_track(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        track_id = _spotify_resource_id(source_url, "track")
        client, token = _spotify_access(request)
        track = client.track_details(token, track_id)
        resource = {"name": f"Spotify — {track.get('name') or 'Track'}"}
        playlist, _count = _save_spotify_playlist(
            _profile(request), resource, [{"item": track}], source_url,
        )
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Трек добавлен в библиотеку: {playlist.title}.")
    return redirect("library")


@require_POST
def import_spotify_library(request):
    try:
        client, token = _spotify_access(request)
        resources = client.my_playlists(token)
        profile = _profile(request)
        imported = 0
        track_count = 0
        skipped = 0
        for resource in resources[:30]:
            playlist_id = resource.get("id")
            if not playlist_id:
                continue
            try:
                entries = client.get_playlist_items(token, playlist_id)
                count = len(entries)
                if count:
                    _save_spotify_playlist(
                        profile,
                        resource,
                        entries,
                        (resource.get("external_urls") or {}).get("spotify", ""),
                    )
                    imported += 1
                    track_count += count
            except TransferError:
                skipped += 1
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(
        request,
        f"Spotify: импортировано плейлистов {imported}, композиций {track_count}; пропущено недоступных плейлистов: {skipped}.",
    )
    return redirect("library")
