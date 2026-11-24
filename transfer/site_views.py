from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .credentials import get_session_fingerprint
from .library_views import _profile
from .models import LibraryPlaylist, LibraryTransfer, TransferJob


@never_cache
@require_GET
def landing(request):
    return render(request, "transfer/landing.html")


@login_required
@never_cache
@require_GET
def dashboard(request):
    profile = _profile(request)
    playlists = LibraryPlaylist.objects.filter(profile=profile).prefetch_related("tracks")[:4]
    return render(request, "transfer/dashboard.html", {
        "recent_playlists": playlists,
        "recent_jobs": TransferJob.objects.filter(
            session_fingerprint=get_session_fingerprint(request)
        )[:5],
    })


@login_required
@never_cache
@require_GET
def library(request):
    profile = _profile(request)
    playlists = LibraryPlaylist.objects.filter(profile=profile).prefetch_related("tracks")
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
    tracks = list(playlist.tracks.all())
    playback_tracks = [{
        "provider": "local" if track.audio_file else (track.source_provider or playlist.provider),
        "id": track.external_id,
        "url": reverse("library_stream_local_track", kwargs={"track_id": track.pk}) if track.audio_file else track.external_url,
        "title": track.title, "artist": track.artist,
        "cover": track.cover_url, "duration": track.duration_ms,
    } for track in tracks]
    return render(request, "transfer/playlist_detail.html", {
        "playlist": playlist, "playback_tracks": playback_tracks,
    })


@login_required
@never_cache
@require_GET
def connections(request):
    return render(request, "transfer/connections.html", {
        "spotify_configured": bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET),
        "soundcloud_configured": bool(settings.SOUNDCLOUD_CLIENT_ID and settings.SOUNDCLOUD_CLIENT_SECRET),
    })


@login_required
@never_cache
@require_GET
def transfers(request):
    return render(request, "transfer/transfers.html", {
        "jobs": TransferJob.objects.filter(
            session_fingerprint=get_session_fingerprint(request)
        )[:50],
        "playlists": LibraryPlaylist.objects.filter(profile=_profile(request)),
        "library_transfers": LibraryTransfer.objects.filter(profile=_profile(request)).select_related("source_playlist", "target_playlist")[:50],
    })


@login_required
@never_cache
@require_GET
def profile(request):
    return render(request, "transfer/profile.html")
