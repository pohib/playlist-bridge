"""SoundCloud upload endpoint and audio file signature validation."""

from pathlib import Path

from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .library_support import _profile, _soundcloud_access
from .models import LibraryPlaylist, LibraryTrack
from .services import TransferError


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


def _has_audio_file_signature(uploaded, extension):
    """Check file bytes instead of trusting the browser-supplied MIME type."""
    signatures = {
        ".wav": lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE",
        ".flac": lambda data: data.startswith(b"fLaC"),
        ".aiff": lambda data: len(data) >= 12 and data[:4] == b"FORM" and data[8:12] in {b"AIFF", b"AIFC"},
        ".aif": lambda data: len(data) >= 12 and data[:4] == b"FORM" and data[8:12] in {b"AIFF", b"AIFC"},
        ".ogg": lambda data: data.startswith(b"OggS"),
        ".amr": lambda data: data.startswith(b"#!AMR"),
        ".wma": lambda data: data.startswith(bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")),
        ".aac": lambda data: len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xF6) == 0xF0,
        ".mp3": lambda data: data.startswith(b"ID3") or (
            len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
        ),
        ".mp2": lambda data: len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0,
    }
    checker = signatures.get(extension)
    if checker is None:
        return False
    try:
        header = uploaded.read(16)
        uploaded.seek(0)
    except (AttributeError, OSError):
        return False
    return checker(header)


@require_POST
def upload_track_to_soundcloud(request):
    uploaded = request.FILES.get("audio_file")
    title = (request.POST.get("title") or "").strip()
    artist = (request.POST.get("artist") or "").strip()
    description = (request.POST.get("description") or "").strip()
    allowed_extensions = {".mp3", ".wav", ".flac", ".aiff", ".aif", ".ogg", ".aac", ".amr", ".wma", ".mp2"}
    if not uploaded or not title or not artist or len(title) > 100 or len(artist) > 100:
        messages.error(request, "Выбери аудиофайл и укажи название и исполнителя.")
        return redirect("library")
    extension = Path(uploaded.name).suffix.lower()
    if extension not in allowed_extensions or uploaded.size > 100 * 1024 * 1024:
        messages.error(request, "Поддерживаются аудиофайлы до 100 МБ в форматах MP3, WAV, FLAC, AIFF, OGG, AAC, AMR, WMA и MP2.")
        return redirect("library")
    if not _has_audio_file_signature(uploaded, extension):
        messages.error(request, "Содержимое файла не соответствует заявленному аудиоформату.")
        return redirect("library")
    try:
        client, token = _soundcloud_access(request)
        result = client.upload_track(token, uploaded, title, artist, description)
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("library")

    profile = _profile(request)
    permalink = str(result.get("permalink_url") or "")
    playlist = LibraryPlaylist.objects.create(
        profile=profile, title=title[:120], provider=LibraryPlaylist.Provider.SOUNDCLOUD,
        external_url=permalink, description="Загружено в SoundCloud",
    )
    LibraryTrack.objects.create(
        playlist=playlist, title=title[:180], artist=artist[:180],
        duration_ms=max(0, int(result.get("duration") or 0)),
        external_id=str(result["id"]), external_url=permalink, position=0,
    )
    messages.success(request, f"Трек «{title}» загружен в SoundCloud и добавлен в библиотеку.")
    return redirect("library")
