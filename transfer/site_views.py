from urllib.parse import quote, urljoin, urlsplit

import requests

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound
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
    playlists = list(LibraryPlaylist.objects.filter(profile=profile).prefetch_related("tracks"))
    for playlist in playlists:
        playlist.playback_id = f"library-playback-{playlist.pk}"
        tracks = list(playlist.tracks.all())
        for track in tracks:
            track.cover_proxy_url = (
                reverse("library_cover_proxy") + "?url=" + quote(track.cover_url, safe="")
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
            reverse("library_cover_proxy") + "?url=" + quote(track.cover_url, safe="")
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


@login_required
@require_GET
def library_cover_proxy(request):
    """Serve approved provider artwork from our origin to honor the strict image CSP."""
    allowed_domains = (
        "userapi.com", "mycdn.me", "vk.com", "vk.ru", "vk.me", "vkuserphoto.ru", "vkuseraudio.net", "okcdn.ru",
        "scdn.co", "sndcdn.com", "spotifycdn.com", "spotify.com",
    )

    def allowed_url(value):
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        return (
            parsed.scheme == "https"
            and bool(host)
            and not parsed.username
            and not parsed.password
            and any(host == domain or host.endswith("." + domain) for domain in allowed_domains)
        )

    current_url = request.GET.get("url", "")
    if not allowed_url(current_url):
        return HttpResponseBadRequest("Unsupported artwork source.")

    for _ in range(4):
        if not allowed_url(current_url):
            return HttpResponseBadRequest("Unsupported artwork redirect.")
        try:
            upstream = requests.get(
                current_url,
                headers={"User-Agent": "Mozilla/5.0 PlaylistBridge/1.0", "Accept": "image/avif,image/webp,image/*"},
                timeout=(5, 12),
                stream=True,
                allow_redirects=False,
            )
        except requests.RequestException:
            return HttpResponseNotFound("Artwork is temporarily unavailable.")

        if upstream.status_code in {301, 302, 303, 307, 308}:
            location = upstream.headers.get("Location")
            upstream.close()
            if not location:
                return HttpResponseNotFound("Artwork redirect is invalid.")
            current_url = urljoin(current_url, location)
            continue
        if upstream.status_code != 200:
            upstream.close()
            return HttpResponseNotFound("Artwork is unavailable.")

        content_type = upstream.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}:
            upstream.close()
            return HttpResponseBadRequest("Unsupported artwork content type.")

        body = bytearray()
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > 6 * 1024 * 1024:
                    return HttpResponseBadRequest("Artwork is too large.")
        finally:
            upstream.close()

        response = HttpResponse(bytes(body), content_type=content_type)
        response["Cache-Control"] = "private, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    return HttpResponseNotFound("Too many artwork redirects.")
