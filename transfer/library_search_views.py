"""Library source opening and cross-provider search endpoints."""

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from .library_support import _profile, _soundcloud_access, _spotify_access
from .models import LibraryPlaylist, LibraryTrack
from .services import TransferError
from .services.library_source_links import safe_provider_source_url
from .services.library_source_search import (
    external_music_search_result,
    soundcloud_library_search_results,
    spotify_library_search_results,
)


@require_GET
def open_playlist_source(request, playlist_id):
    playlist = get_object_or_404(
        LibraryPlaylist, pk=playlist_id, profile=_profile(request)
    )
    source_url = safe_provider_source_url(playlist.external_url, playlist.provider)
    if not source_url:
        return redirect("library")
    return HttpResponseRedirect(source_url)


@require_GET
def open_track_source(request, track_id):
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist__profile"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    source_url = safe_provider_source_url(
        track.external_url,
        track.playlist.provider,
    )
    if not source_url:
        return redirect("library")
    return HttpResponseRedirect(source_url)


@login_required
@require_POST
def search_library_sources(request):
    """Search supported providers for a library track; external-only providers return search links."""
    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        return JsonResponse({"error": "Некорректный JSON запроса."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Некорректный формат запроса."}, status=400)
    title = str(payload.get("title") or "").strip()
    artist = str(payload.get("artist") or "").strip()
    requested = payload.get("providers", ["auto"])
    if not title or len(title) > 180 or len(artist) > 180:
        return JsonResponse({"error": "Укажи название трека и корректного исполнителя."}, status=400)
    allowed = {"auto", "vk", "spotify", "soundcloud", "youtube_music", "apple_music"}
    if not isinstance(requested, list) or not requested or any(
        not isinstance(item, str) or item not in allowed for item in requested
    ):
        return JsonResponse({"error": "Выбраны неподдерживаемые источники."}, status=400)
    providers = (
        ["spotify", "soundcloud", "youtube_music", "apple_music"]
        if "auto" in requested
        else list(dict.fromkeys(requested))
    )
    query = f"{artist} {title}".strip()
    results, statuses = [], {}
    for provider in providers:
        try:
            if provider == "vk":
                # VK audio.search is unavailable with anonymous tokens (API error 28).
                # Public playlist imports and audio.getById remain supported.
                statuses[provider] = (
                    "VK используется для воспроизведения импортированных композиций; "
                    "поиск по каталогу VK через анонимный API недоступен."
                )
            elif provider == "spotify":
                client, token = _spotify_access(request)
                results.extend(spotify_library_search_results(
                    client.search_tracks(token, query)
                ))
                statuses[provider] = "ok"
            elif provider == "soundcloud":
                client, token = _soundcloud_access(request)
                results.extend(soundcloud_library_search_results(
                    client.search_tracks(token, query),
                    fallback_artist=artist,
                ))
                statuses[provider] = "ok"
            elif provider in {"youtube_music", "apple_music"}:
                results.append(external_music_search_result(provider, query))
                statuses[provider] = (
                    "Доступна ссылка на поиск; публичный API для получения результатов "
                    "не подключён."
                )
        except TransferError as exc:
            statuses[provider] = str(exc)
        except (AttributeError, KeyError, TypeError, ValueError):
            statuses[provider] = "Провайдер вернул данные неизвестного формата."
    return JsonResponse({
        "results": results[:60],
        "statuses": statuses,
        "query": query,
    })
