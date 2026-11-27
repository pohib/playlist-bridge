"""SoundCloud playlist, track, and library import endpoints."""

from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .library_support import _profile, _soundcloud_access
from .models import LibraryPlaylist
from .services.library_management import append_provider_track
from .services import TransferError
from .services.library_imports import save_soundcloud_playlist, validate_soundcloud_permalink

# Keep the previous private helper names importable for compatibility.
_validate_soundcloud_permalink = validate_soundcloud_permalink
_save_soundcloud_playlist = save_soundcloud_playlist


@require_POST
def import_soundcloud_playlist(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        source_url = _validate_soundcloud_permalink(source_url)
        client, token = _soundcloud_access(request)
        resource = client.resolve(token, source_url)
        if resource.get("kind") != "playlist" and "tracks" not in resource:
            raise TransferError("Ссылка ведёт не на плейлист SoundCloud.")
        resource_id = resource.get("id")
        tracks = client.playlist_tracks(token, resource_id) if resource_id else resource.get("tracks", [])
        playlist, count = _save_soundcloud_playlist(_profile(request), resource, tracks, source_url)
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Импортирован плейлист «{playlist.title}»: {count} композиций.")
    return redirect("library")


@require_POST
def import_soundcloud_track(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        source_url = _validate_soundcloud_permalink(source_url)
        client, token = _soundcloud_access(request)
        resource = client.resolve(token, source_url)
        if resource.get("kind") != "track" and "duration" not in resource:
            raise TransferError("Ссылка ведёт не на трек SoundCloud.")
        profile = _profile(request)
        playlist_id = (request.POST.get("playlist_id") or "").strip()
        playlist = (
            get_object_or_404(LibraryPlaylist, pk=playlist_id, profile=profile)
            if playlist_id else None
        )
        if playlist:
            user = resource.get("user")
            if not isinstance(user, dict):
                user = {}
            append_provider_track(
                playlist,
                title=resource.get("title") or "Unknown track",
                artist=resource.get("metadata_artist") or user.get("username") or "Unknown artist",
                provider=LibraryPlaylist.Provider.SOUNDCLOUD,
                external_id=resource.get("id", ""),
                external_url=resource.get("permalink_url") or source_url,
                duration_ms=resource.get("duration"),
                cover_url=resource.get("artwork_url") or "",
            )
        else:
            playlist, _count = _save_soundcloud_playlist(
                profile,
                {"title": f"SoundCloud — {resource.get('title') or 'Track'}"},
                [resource],
                source_url,
            )
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Композиция добавлена в «{playlist.title}».")
    return redirect("playlist_detail", playlist_id=playlist.pk)


@require_POST
def import_soundcloud_library(request):
    try:
        client, token = _soundcloud_access(request)
        resources = client.my_playlists(token)
        profile = _profile(request)
        imported = 0
        track_count = 0
        for resource in resources[:30]:
            resource_id = resource.get("id")
            if not resource_id:
                continue
            tracks = client.playlist_tracks(token, resource_id)
            source_url = resource.get("permalink_url") or ""
            if source_url:
                _save_soundcloud_playlist(profile, resource, tracks, source_url)
                imported += 1
                track_count += len(tracks)
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Импортировано плейлистов: {imported}; композиций: {track_count}.")
    return redirect("library")
