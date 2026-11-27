"""VK-specific playback HTTP endpoints."""

# ruff: noqa: I001 -- keep the service-module imports together for explicit aliases.

import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .library_support import _profile
from .models import LibraryPlaylist, LibraryTrack
from .services import library_vk_playback, vk_client


VKClient = vk_client.VKClient
VKPlaybackError = library_vk_playback.VKPlaybackError
open_vk_track_audio = library_vk_playback.open_vk_track_audio
resolve_vk_track_stream = library_vk_playback.resolve_vk_track_stream
logger = logging.getLogger(__name__)


@login_required
@require_POST
def get_vk_track_stream(request, track_id):
    """Validate a VK stream and return its same-origin playback proxy URL."""
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
    try:
        resolve_vk_track_stream(
            api, track.playlist, track.external_id, stream_format
        )
    except VKPlaybackError as exc:
        message = (
            "Неподдерживаемый формат потока."
            if exc.status_code == 400
            else (
                "Не удалось подключиться к CDN VK. Попробуй запустить трек ещё раз."
                if exc.status_code == 502
                else "VK не предоставил аудиопоток. Попробуй запустить трек позже."
            )
        )
        response = JsonResponse({"error": message}, status=exc.status_code)
        response["Cache-Control"] = "private, no-store"
        return response
    proxy_url = reverse("library_vk_track_audio", kwargs={"track_id": track.pk})
    response = JsonResponse({
        "url": f"{proxy_url}?format={stream_format}",
        "format": stream_format,
    })
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    return response


@login_required
@require_GET
def stream_vk_track_audio(request, track_id):
    """Proxy a fresh VK audio stream with browser-friendly Range handling."""
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    if (track.source_provider or track.playlist.provider) != LibraryPlaylist.Provider.VK:
        raise Http404("VK track not found")

    stream_format = request.GET.get("format", "mp3")
    if stream_format not in {"mp3", "hls_ts"}:
        return JsonResponse({"error": "Неподдерживаемый формат потока."}, status=400)

    api = VKClient(version=settings.VK_API_VERSION)
    api.token_provider.referer = track.playlist.external_url or "https://vk.ru/"
    try:
        upstream = open_vk_track_audio(
            api,
            track.playlist,
            track.external_id,
            request.headers.get("Range", ""),
            stream_format,
        )
    except VKPlaybackError as exc:
        if exc.status_code == 422:
            logger.info(
                "VK %s stream unavailable for track %s",
                stream_format,
                track.pk,
            )
        message = (
            "Неподдерживаемый формат потока."
            if exc.status_code == 400
            else (
                "Не удалось подключиться к CDN VK. Попробуй запустить трек ещё раз."
                if exc.status_code == 502
                else "VK не предоставил аудиопоток. Попробуй запустить трек позже."
            )
        )
        response = JsonResponse({"error": message}, status=exc.status_code)
        response["Cache-Control"] = "private, no-store"
        return response

    def chunks():
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    upstream_type = upstream.headers.get("Content-Type", "").split(";", 1)[0].lower()
    allowed_types = {
        "audio/mpeg",
        "audio/mp4",
        "audio/aac",
        "audio/aacp",
        "audio/ogg",
        "video/mp2t",
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
    }
    content_type = upstream_type if upstream_type in allowed_types else (
        "audio/mpeg" if stream_format == "mp3" else "video/mp2t"
    )
    response = StreamingHttpResponse(
        chunks(), status=upstream.status_code, content_type=content_type
    )
    response["Accept-Ranges"] = upstream.headers.get("Accept-Ranges", "bytes")
    content_range = upstream.headers.get("Content-Range")
    if content_range:
        response["Content-Range"] = content_range
    content_length = upstream.headers.get("Content-Length")
    if content_length:
        response["Content-Length"] = content_length
    response["Content-Disposition"] = "inline"
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
