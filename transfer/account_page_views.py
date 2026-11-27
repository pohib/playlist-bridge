"""Account, connections, transfer history and pop-out player pages."""

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .library_support import _profile
from .models import LibraryPlaylist, LibraryTrack, LibraryTransfer, OAuthCredential, TransferJob
from .services.credential_service import get_session_fingerprint


@login_required
@never_cache
@require_GET
def connections(request):
    """Manage external music-service authorizations for the current account."""
    fingerprint = get_session_fingerprint(request)
    connected = set(
        OAuthCredential.objects.filter(session_fingerprint=fingerprint)
        .values_list("provider", flat=True)
    )
    return render(request, "transfer/connections.html", {
        "library_spotify_connected": "spotify" in connected,
        "library_soundcloud_connected": "soundcloud" in connected,
        "spotify_configured": bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET),
        "soundcloud_configured": bool(settings.SOUNDCLOUD_CLIENT_ID and settings.SOUNDCLOUD_CLIENT_SECRET),
        "oauth_success": request.session.pop("oauth_success", ""),
        "oauth_error": request.session.pop("oauth_error", ""),
    })


@login_required
@never_cache
@require_GET
def transfers(request):
    profile = _profile(request)
    return render(request, "transfer/transfers.html", {
        "jobs": TransferJob.objects.filter(
            session_fingerprint=get_session_fingerprint(request)
        )[:50],
        "playlists": LibraryPlaylist.objects.filter(profile=profile),
        "library_transfers": LibraryTransfer.objects.filter(profile=profile).select_related(
            "source_playlist", "target_playlist"
        )[:50],
    })


@login_required
@never_cache
@require_GET
def profile(request):
    profile = _profile(request)
    playlists = LibraryPlaylist.objects.filter(profile=profile)
    connected = set(
        OAuthCredential.objects.filter(session_fingerprint=get_session_fingerprint(request))
        .values_list("provider", flat=True)
    )
    return render(request, "transfer/profile.html", {
        "library_profile": profile,
        "playlist_count": playlists.count(),
        "track_count": LibraryTrack.objects.filter(playlist__profile=profile).count(),
        "transfer_count": LibraryTransfer.objects.filter(profile=profile).count(),
        "recent_playlists": playlists.order_by("-updated_at")[:4],
        "spotify_connected": "spotify" in connected,
        "soundcloud_connected": "soundcloud" in connected,
    })


@login_required
@never_cache
@require_GET
def player_popout(request):
    """Render the standalone, authenticated pop-out music player."""
    return render(request, "transfer/player_popout.html")
