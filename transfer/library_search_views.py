"""Library source opening and cross-provider search endpoints."""

import json
from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from .library_support import _profile, _soundcloud_access, _spotify_access
from .models import LibraryPlaylist, LibraryTrack
from .services import TransferError


@require_GET
def open_playlist_source(request, playlist_id):
    from django.http import HttpResponseRedirect

    playlist = get_object_or_404(
        LibraryPlaylist, pk=playlist_id, profile=_profile(request)
    )
    from urllib.parse import urlparse

    allowed_hosts = {
        "vk": {"vk.com", "www.vk.com", "m.vk.com", "vk.ru"},
        "spotify": {"open.spotify.com", "www.open.spotify.com"},
        "soundcloud": {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"},
        "youtube_music": {"music.youtube.com", "www.youtube.com", "youtube.com"},
        "apple_music": {"music.apple.com"},
    }
    parsed = urlparse(playlist.external_url)
    try:
        port = parsed.port
    except ValueError:
        return redirect("library")
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts.get(playlist.provider, set())
        or port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        return redirect("library")
    return HttpResponseRedirect(playlist.external_url)


@require_GET
def open_track_source(request, track_id):
    from django.http import HttpResponseRedirect

    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist__profile"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    from urllib.parse import urlparse

    provider = track.playlist.provider
    allowed_hosts = {
        "vk": {"vk.com", "www.vk.com", "m.vk.com", "vk.ru"},
        "spotify": {"open.spotify.com", "www.open.spotify.com"},
        "soundcloud": {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"},
        "youtube_music": {"music.youtube.com", "www.youtube.com", "youtube.com"},
        "apple_music": {"music.apple.com"},
    }
    parsed = urlparse(track.external_url)
    try:
        port = parsed.port
    except ValueError:
        return redirect("library")
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts.get(provider, set())
        or port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        return redirect("library")
    return HttpResponseRedirect(track.external_url)


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
    if not isinstance(requested, list) or not requested or any(not isinstance(item, str) or item not in allowed for item in requested):
        return JsonResponse({"error": "Выбраны неподдерживаемые источники."}, status=400)
    providers = ["spotify", "soundcloud", "youtube_music", "apple_music"] if "auto" in requested else list(dict.fromkeys(requested))
    query = f"{artist} {title}".strip()
    results, statuses = [], {}
    for provider in providers:
        try:
            if provider == "vk":
                # VK audio.search is unavailable with anonymous tokens (API error 28).
                # Public playlist imports and audio.getById remain supported.
                statuses[provider] = "VK используется для воспроизведения импортированных композиций; поиск по каталогу VK через анонимный API недоступен."
            elif provider == "spotify":
                client, token = _spotify_access(request)
                for track in client.search_tracks(token, query):
                    artists = ", ".join(item.get("name", "") for item in track.get("artists", []) if item.get("name"))
                    external = (track.get("external_urls") or {}).get("spotify", "")
                    images = (track.get("album") or {}).get("images") or []
                    if external:
                        results.append({
                            "provider": "spotify", "id": track.get("id", ""),
                            "title": track.get("name", ""), "artist": artists,
                            "cover": images[0].get("url", "") if images else "",
                            "url": external, "playable": True,
                        })
                statuses[provider] = "ok"
            elif provider == "soundcloud":
                client, token = _soundcloud_access(request)
                for track in client.search_tracks(token, query):
                    permalink = track.get("permalink_url", "")
                    if permalink:
                        user = track.get("user") or {}
                        results.append({
                            "provider": "soundcloud", "id": str(track.get("id", "")),
                            "title": track.get("title", ""), "artist": user.get("username", artist),
                            "cover": track.get("artwork_url", ""), "url": permalink,
                            "playable": True,
                        })
                statuses[provider] = "ok"
            elif provider in {"youtube_music", "apple_music"}:
                from urllib.parse import quote_plus
                search_url = (
                    "https://music.youtube.com/search?q=" if provider == "youtube_music"
                    else "https://music.apple.com/search?term="
                ) + quote_plus(query)
                results.append({
                    "provider": provider, "title": "Открыть поиск в " + (
                        "YouTube Music" if provider == "youtube_music" else "Apple Music"
                    ),
                    "artist": query, "cover": "", "url": search_url,
                    "playable": False, "search_only": True,
                })
                statuses[provider] = "Доступна ссылка на поиск; публичный API для получения результатов не подключён."
        except TransferError as exc:
            statuses[provider] = str(exc)
        except (AttributeError, KeyError, TypeError, ValueError):
            statuses[provider] = "Провайдер вернул данные неизвестного формата."
    return JsonResponse({"results": results[:60], "statuses": statuses, "query": query})
