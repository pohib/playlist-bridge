from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .credentials import get_session_fingerprint
from .library_views import _profile
from .models import LibraryPlaylist, TransferJob


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
    playlists = LibraryPlaylist.objects.filter(profile=profile).annotate().prefetch_related("tracks")
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
    return render(request, "transfer/playlist_detail.html", {"playlist": playlist})


@login_required
@never_cache
@require_GET
def connections(request):
    return render(request, "transfer/connections.html", {
        "spotify_configured": bool(__import__("django.conf").conf.settings.SPOTIFY_CLIENT_ID and __import__("django.conf").conf.settings.SPOTIFY_CLIENT_SECRET),
        "vk_configured": bool(__import__("django.conf").conf.settings.VK_ID_CLIENT_ID),
        "soundcloud_configured": bool(__import__("django.conf").conf.settings.SOUNDCLOUD_CLIENT_ID and __import__("django.conf").conf.settings.SOUNDCLOUD_CLIENT_SECRET),
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
    })


@login_required
@never_cache
@require_GET
def profile(request):
    return render(request, "transfer/profile.html")
