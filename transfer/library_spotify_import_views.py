"""Spotify playlist, track, and library import endpoints."""

from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .library_support import _profile, _spotify_access
from .services import TransferError
from .services.library_imports import save_spotify_playlist, spotify_resource_id

# Keep the previous private helper names importable for compatibility.
_spotify_resource_id = spotify_resource_id
_save_spotify_playlist = save_spotify_playlist


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
