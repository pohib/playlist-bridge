from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .credentials import get_session_fingerprint
from .library_support import _profile
from .models import LibraryPlaylist, LibraryTrack, LibraryTransfer, OAuthCredential, TransferJob


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
    playlists = list(LibraryPlaylist.objects.filter(profile=profile).prefetch_related("tracks"))
    for playlist in playlists:
        playlist.playback_id = f"library-playback-{playlist.pk}"
        tracks = list(playlist.tracks.all())
        for track in tracks:
            track.cover_proxy_url = (
                reverse("library_cover_proxy") + "?track_id=" + str(track.pk)
                if track.cover_url else ""
            )
        playlist.cover_proxy_url = next(
            (track.cover_proxy_url for track in tracks if track.cover_proxy_url), ""
        )
        playlist.playback_data = [{
            "provider": "local" if track.audio_file else (track.source_provider or playlist.provider),
            "id": track.external_id,
            "url": reverse("library_stream_local_track", kwargs={"track_id": track.pk}) if track.audio_file else track.external_url,
            "title": track.title, "artist": track.artist, "cover": track.cover_proxy_url,
            "duration": track.duration_ms,
            "stream_url": reverse("library_vk_track_audio", kwargs={"track_id": track.pk})
                if (track.source_provider or playlist.provider) == LibraryPlaylist.Provider.VK and not track.audio_file else "",
            "stream_resolve_url": reverse("library_vk_track_stream", kwargs={"track_id": track.pk})
                if (track.source_provider or playlist.provider) == LibraryPlaylist.Provider.VK and not track.audio_file else "",
        } for track in tracks]
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
    for track in tracks:
        track.cover_proxy_url = (
            reverse("library_cover_proxy") + "?track_id=" + str(track.pk)
            if track.cover_url else ""
        )
    playback_tracks = [{
        "provider": "local" if track.audio_file else (track.source_provider or playlist.provider),
        "id": track.external_id,
        "url": reverse("library_stream_local_track", kwargs={"track_id": track.pk}) if track.audio_file else track.external_url,
        "title": track.title, "artist": track.artist,
        "cover": track.cover_proxy_url, "duration": track.duration_ms,
        "stream_url": reverse("library_vk_track_audio", kwargs={"track_id": track.pk}) if (track.source_provider or playlist.provider) == LibraryPlaylist.Provider.VK and not track.audio_file else "",
        "stream_resolve_url": reverse("library_vk_track_stream", kwargs={"track_id": track.pk}) if (track.source_provider or playlist.provider) == LibraryPlaylist.Provider.VK and not track.audio_file else "",
    } for track in tracks]
    return render(request, "transfer/playlist_detail.html", {
        "playlist": playlist, "playback_tracks": playback_tracks,
    })


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
