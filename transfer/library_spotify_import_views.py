"""Spotify playlist, track, and library import endpoints."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .library_support import _profile, _spotify_access
from .models import LibraryPlaylist
from .services import library_import_spotify
from .services.common import TransferError

# Keep the previous private helper names importable for compatibility.
_spotify_resource_id = library_import_spotify.spotify_resource_id
_save_spotify_playlist = library_import_spotify.save_spotify_playlist


@require_POST
def import_spotify_playlist(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        playlist_id = _spotify_resource_id(source_url, "playlist")
        client, token = _spotify_access(request)
        playlist, count = library_import_spotify.import_spotify_playlist(
            _profile(request),
            client,
            token,
            playlist_id,
            source_url,
        )
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Импортирован Spotify-плейлист «{playlist.title}»: {count} композиций.")
    return redirect("library")


@require_POST
def import_spotify_track(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        client, token = _spotify_access(request)
        profile = _profile(request)
        playlist_id = (request.POST.get("playlist_id") or "").strip()
        playlist = (
            get_object_or_404(LibraryPlaylist, pk=playlist_id, profile=profile)
            if playlist_id else None
        )
        playlist = library_import_spotify.import_spotify_track(
            profile,
            client,
            token,
            source_url,
            playlist=playlist,
        )
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Трек добавлен в «{playlist.title}».")
    return redirect("playlist_detail", playlist_id=playlist.pk)


@require_POST
def import_spotify_library(request):
    try:
        client, token = _spotify_access(request)
        imported, track_count, skipped = library_import_spotify.import_spotify_library(
            _profile(request),
            client,
            token,
        )
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(
        request,
        f"Spotify: импортировано плейлистов {imported}, композиций {track_count}; пропущено недоступных плейлистов: {skipped}.",
    )
    return redirect("library")
