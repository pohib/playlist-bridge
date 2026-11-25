"""Library playback and audio streaming endpoints."""

import json
import logging
import mimetypes
import re

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .library_support import _profile
from .models import LibraryPlaylist, LibraryTrack
from .services import TransferError, VKClient

logger = logging.getLogger(__name__)


@login_required
def stream_local_track(request, track_id):
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist__profile"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    if not track.audio_file:
        raise Http404("У композиции нет локального аудиофайла.")
    content_type = mimetypes.guess_type(track.audio_file.name)[0] or "application/octet-stream"
    response = FileResponse(track.audio_file.open("rb"), content_type=content_type, as_attachment=False)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def get_vk_track_stream(request, track_id):
    """Resolve a short-lived VK CDN URL only when the user starts a track."""
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    if (track.source_provider or track.playlist.provider) != LibraryPlaylist.Provider.VK:
        return JsonResponse({"error": "Эта композиция не относится к VK."}, status=400)
    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        return JsonResponse({"error": "Некорректный запрос потока."}, status=400)
    stream_format = payload.get("format", "mp3") if isinstance(payload, dict) else "mp3"
    if stream_format not in {"mp3", "hls_ts"}:
        return JsonResponse({"error": "Неподдерживаемый формат потока."}, status=400)
    api = VKClient(version=settings.VK_API_VERSION)
    api.token_provider.referer = track.playlist.external_url or "https://vk.ru/"
    audio_id = track.external_id
    if re.fullmatch(r"-?\d+_\d+", audio_id) and "/music/playlist/" in track.playlist.external_url:
        try:
            audio_id = api.resolve_playlist_audio_id(track.playlist.external_url, audio_id)
        except (ValueError, TransferError) as exc:
            response = JsonResponse({"error": str(exc)}, status=422)
            response["Cache-Control"] = "private, no-store"
            return response
    last_error = None
    for attempt in range(2):
        try:
            stream = api.get_track_stream(audio_id, stream_format)
            response = JsonResponse(stream)
            response["Cache-Control"] = "private, no-store"
            response["Pragma"] = "no-cache"
            return response
        except TransferError as exc:
            last_error = exc
            if "ограничение доступа" in str(exc).lower() or "не предоставил" in str(exc).lower():
                break
            if attempt == 0:
                import time
                time.sleep(0.35)
    response = JsonResponse({"error": str(last_error or "VK временно не выдал аудиопоток.")}, status=422)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def stream_vk_track_audio(request, track_id):
    """Proxy a fresh VK MP3 stream with browser-friendly audio and Range headers."""
    import requests

    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    if (track.source_provider or track.playlist.provider) != LibraryPlaylist.Provider.VK:
        raise Http404("VK track not found")

    api = VKClient(version=settings.VK_API_VERSION)
    api.token_provider.referer = track.playlist.external_url or "https://vk.ru/"
    audio_id = track.external_id
    try:
        if re.fullmatch(r"-?\d+_\d+", audio_id) and "/music/playlist/" in track.playlist.external_url:
            audio_id = api.resolve_playlist_audio_id(track.playlist.external_url, audio_id)

        stream = api.get_track_stream(audio_id, "mp3")
    except (TransferError, ValueError) as exc:
        # VK may not expose an MP3 stream for a track. Return the actual
        # upstream reason instead of turning it into an unhandled HTTP 500.
        logger.info("VK MP3 stream unavailable for track %s: %s", track.pk, exc)
        response = JsonResponse({"error": str(exc)}, status=422)
        response["Cache-Control"] = "private, no-store"
        return response
    headers = {
        **api.token_provider.BROWSER_HEADERS,
        "Accept": "audio/mpeg,audio/*;q=0.9,*/*;q=0.8",
        "Referer": api.token_provider.referer,
    }
    requested_range = request.headers.get("Range")
    if requested_range:
        headers["Range"] = requested_range

    try:
        upstream = requests.get(
            stream["url"], headers=headers, stream=True,
            timeout=(8, 45), allow_redirects=False,
        )
    except requests.RequestException:
        logger.exception("VK CDN stream request failed for track %s", track.pk)
        return JsonResponse({"error": "Не удалось подключиться к CDN VK. Попробуй запустить трек ещё раз."}, status=502)
    if upstream.status_code not in {200, 206}:
        upstream.close()
        return JsonResponse({"error": "VK CDN не смог отдать аудиопоток."}, status=502)

    content_range = upstream.headers.get("Content-Range")
    if upstream.status_code == 206 and not content_range:
        upstream.close()
        return JsonResponse({"error": "VK CDN вернул некорректный диапазон аудио."}, status=502)

    def chunks():
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    response = StreamingHttpResponse(chunks(), status=upstream.status_code, content_type="audio/mpeg")
    response["Accept-Ranges"] = upstream.headers.get("Accept-Ranges", "bytes")
    if content_range:
        response["Content-Range"] = content_range
    content_length = upstream.headers.get("Content-Length")
    if content_length:
        response["Content-Length"] = content_length
    response["Content-Disposition"] = "inline"
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
