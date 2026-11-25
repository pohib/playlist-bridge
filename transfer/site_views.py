from urllib.parse import urljoin, urlsplit

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .credentials import get_session_fingerprint
from .library_views import _profile
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
@require_GET
def library_cover_proxy(request):
    """Serve approved provider artwork from our origin to honor the strict image CSP."""
    allowed_domains = (
        "userapi.com", "mycdn.me", "vk.com", "vk.ru", "vk.me", "vkuserphoto.ru", "vkuseraudio.net", "okcdn.ru",
        "scdn.co", "sndcdn.com", "spotifycdn.com", "spotify.com",
    )

    def allowed_url(value):
        if not isinstance(value, str) or not value or len(value) > 2048:
            return False
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            return False
        host = (parsed.hostname or "").lower().rstrip(".")
        return (
            parsed.scheme == "https"
            and port in (None, 443)
            and bool(host)
            and not parsed.username
            and not parsed.password
            and any(host == domain or host.endswith("." + domain) for domain in allowed_domains)
        )

    track_id = request.GET.get("track_id", "")
    if not track_id or len(track_id) > 36:
        return HttpResponseBadRequest("Invalid artwork reference.")
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    current_url = track.cover_url
    if not allowed_url(current_url):
        return HttpResponseNotFound("Artwork source is not supported.")

    for _ in range(8):
        if not allowed_url(current_url):
            return HttpResponseBadRequest("Unsupported artwork redirect.")
        try:
            upstream = requests.get(
                current_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 PlaylistBridge/1.0",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "Referer": "https://vk.ru/",
                    "Origin": "https://vk.ru",
                },
                timeout=(5, 15),
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

        content_length = upstream.headers.get("Content-Length", "")
        if content_length.isdigit() and int(content_length) > 6 * 1024 * 1024:
            upstream.close()
            return HttpResponseBadRequest("Artwork is too large.")

        content_type = upstream.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type == "image/jpg":
            content_type = "image/jpeg"
        body = bytearray()
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > 6 * 1024 * 1024:
                    return HttpResponseBadRequest("Artwork is too large.")
        except requests.RequestException:
            return HttpResponseNotFound("Artwork is temporarily unavailable.")
        finally:
            upstream.close()

        detected_type = ""
        if body.startswith(bytes.fromhex("FFD8FF")):
            detected_type = "image/jpeg"
        elif body.startswith(bytes.fromhex("89504E470D0A1A0A")):
            detected_type = "image/png"
        elif body.startswith((b"GIF87a", b"GIF89a")):
            detected_type = "image/gif"
        elif len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
            detected_type = "image/webp"
        elif len(body) >= 12 and body[4:8] == b"ftyp" and body[8:12] in {b"avif", b"avis"}:
            detected_type = "image/avif"
        if not detected_type:
            return HttpResponseNotFound("Artwork response is not a supported image.")
        response = HttpResponse(bytes(body), content_type=detected_type)
        response["Cache-Control"] = "private, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    return HttpResponseNotFound("Too many artwork redirects.")
