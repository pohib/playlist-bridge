"""HTTP adapters for track-level library management and local uploads."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .library_support import _profile
from .models import LibraryPlaylist, LibraryTrack
from .services.library_management import (
    LibraryManagementError,
    add_track as add_track_service,
    delete_track as delete_track_service,
    move_track as move_track_service,
    update_track as update_track_service,
    upload_local_track as upload_local_track_service,
)


@require_POST
def move_track(request, playlist_id, track_id):
    playlist = get_object_or_404(
        LibraryPlaylist, pk=playlist_id, profile=_profile(request)
    )
    try:
        moved = move_track_service(
            playlist, track_id, request.POST.get("direction", "")
        )
    except LibraryManagementError as exc:
        messages.error(request, str(exc))
    else:
        if moved:
            messages.success(request, "Порядок композиций обновлён.")
    return redirect("playlist_detail", playlist_id=playlist.pk)


@require_POST
def add_track(request, playlist_id):
    playlist = get_object_or_404(
        LibraryPlaylist, pk=playlist_id, profile=_profile(request)
    )
    try:
        add_track_service(
            playlist,
            title=request.POST.get("title"),
            artist=request.POST.get("artist"),
            album=request.POST.get("album"),
            external_id=request.POST.get("external_id"),
            external_url=request.POST.get("external_url"),
            duration_seconds=(request.POST.get("duration_seconds") or "").strip(),
        )
    except LibraryManagementError as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, "Композиция добавлена.")
    return redirect("library")


@require_POST
def update_track(request, playlist_id, track_id):
    playlist = get_object_or_404(
        LibraryPlaylist, pk=playlist_id, profile=_profile(request)
    )
    track = get_object_or_404(LibraryTrack, pk=track_id, playlist=playlist)
    try:
        update_track_service(
            track,
            title=request.POST.get("title"),
            artist=request.POST.get("artist"),
            album=request.POST.get("album"),
        )
    except LibraryManagementError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Данные композиции обновлены.")
    return redirect("playlist_detail", playlist_id=playlist.pk)


@require_POST
def delete_track(request, track_id):
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist__profile"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    delete_track_service(track)
    messages.success(request, "Композиция удалена.")
    return redirect("library")


@require_POST
@login_required
def upload_local_track(request):
    try:
        playlist, track = upload_local_track_service(
            _profile(request),
            title=request.POST.get("title"),
            artist=request.POST.get("artist"),
            uploaded=request.FILES.get("audio_file"),
        )
    except LibraryManagementError as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(
        request, f"Файл «{track.title}» добавлен в локальную библиотеку."
    )
    return redirect("playlist_detail", playlist_id=playlist.pk)
