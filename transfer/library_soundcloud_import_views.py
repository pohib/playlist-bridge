"""SoundCloud playlist, track, and library import endpoints."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .library_support import _profile, _soundcloud_access
from .models import LibraryPlaylist
from .services import library_import_soundcloud
from .services.common import TransferError

# Keep the previous private helper names importable for compatibility.
_validate_soundcloud_permalink = library_import_soundcloud.validate_soundcloud_permalink
_save_soundcloud_playlist = library_import_soundcloud.save_soundcloud_playlist


@require_POST
def import_soundcloud_playlist(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        source_url = _validate_soundcloud_permalink(source_url)
        client, token = _soundcloud_access(request)
        playlist, count = library_import_soundcloud.import_soundcloud_playlist(
            _profile(request),
            client,
            token,
            source_url,
        )
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
        playlist = library_import_soundcloud.save_soundcloud_track(
            profile,
            resource,
            source_url,
            playlist=playlist,
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
        imported, track_count = library_import_soundcloud.import_soundcloud_library(
            _profile(request),
            client,
            token,
        )
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Импортировано плейлистов: {imported}; композиций: {track_count}.")
    return redirect("library")
