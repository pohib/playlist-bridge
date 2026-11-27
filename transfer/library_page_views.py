"""Library page and playlist detail views."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .library_support import _profile
from .models import LibraryPlaylist
from .services.library_presentation import (
    build_playlist_playback_tracks,
    prepare_library_playlist,
)


@login_required
@never_cache
@require_GET
def library(request):
    profile = _profile(request)
    playlists = list(LibraryPlaylist.objects.filter(profile=profile).prefetch_related("tracks"))
    for playlist in playlists:
        prepare_library_playlist(playlist)
    return render(request, "transfer/library.html", {"playlists": playlists})


@login_required
@never_cache
@require_GET
def playlist_detail(request, playlist_id):
    playlist = get_object_or_404(
        LibraryPlaylist.objects.prefetch_related("tracks"),
        pk=playlist_id,
        profile=_profile(request),
    )
    playback_tracks = build_playlist_playback_tracks(playlist)
    return render(request, "transfer/playlist_detail.html", {
        "playlist": playlist, "playback_tracks": playback_tracks,
    })
