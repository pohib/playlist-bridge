"""HTTP adapters for playlist-level library management."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .library_support import _profile
from .models import LibraryPlaylist
from .services.library_management import LibraryManagementError
from .services.library_management import create_playlist as create_playlist_service
from .services.library_management import delete_playlist as delete_playlist_service
from .services.library_management import merge_playlists as merge_playlists_service
from .services.library_management import update_playlist as update_playlist_service


@require_POST
def create_playlist(request):
    try:
        create_playlist_service(
            _profile(request),
            title=request.POST.get("title"),
            provider=request.POST.get("provider", LibraryPlaylist.Provider.MANUAL),
            description=request.POST.get("description"),
            external_url=request.POST.get("external_url"),
        )
    except LibraryManagementError as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, "Плейлист добавлен в библиотеку.")
    return redirect("library")


@require_POST
def update_playlist(request, playlist_id):
    playlist = get_object_or_404(
        LibraryPlaylist, pk=playlist_id, profile=_profile(request)
    )
    try:
        update_playlist_service(
            playlist,
            title=request.POST.get("title"),
            description=request.POST.get("description"),
        )
    except LibraryManagementError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Плейлист обновлён.")
    return redirect("playlist_detail", playlist_id=playlist.pk)


@require_POST
def delete_playlist(request, playlist_id):
    playlist = get_object_or_404(
        LibraryPlaylist, pk=playlist_id, profile=_profile(request)
    )
    delete_playlist_service(playlist)
    messages.success(request, "Плейлист и его локальные записи удалены.")
    return redirect("library")


@require_POST
def merge_playlists(request):
    try:
        merged, count = merge_playlists_service(
            _profile(request),
            request.POST.getlist("playlist_ids"),
            request.POST.get("title"),
        )
    except LibraryManagementError as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(
        request,
        f"Создана коллекция «{merged.title}»: {count} уникальных композиций.",
    )
    return redirect("playlist_detail", playlist_id=merged.pk)
