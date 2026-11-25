# ruff: noqa: I001
import json
import logging
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from .services import TransferError, VKClient
from .models import LibraryPlaylist, LibraryTrack

# Provider import handlers remain available through the legacy library module.
from .library_import_views import (
    _save_soundcloud_playlist,  # noqa: F401
    _save_spotify_playlist,  # noqa: F401
    _spotify_resource_id,  # noqa: F401
    _validate_soundcloud_permalink,  # noqa: F401
    import_soundcloud_library,  # noqa: F401
    import_soundcloud_playlist,  # noqa: F401
    import_soundcloud_track,  # noqa: F401
    import_spotify_library,  # noqa: F401
    import_spotify_playlist,  # noqa: F401
    import_spotify_track,  # noqa: F401
    import_vk_playlist,  # noqa: F401
    import_vk_track,  # noqa: F401
    refresh_vk_artwork,  # noqa: F401
)

# Playback handlers remain available through the legacy library module.
from .library_playback_views import (
    get_vk_track_stream,  # noqa: F401
    stream_local_track,  # noqa: F401
    stream_vk_track_audio,  # noqa: F401
)

from .library_support import _profile, _safe_candidate_url, _soundcloud_access, _spotify_access  # noqa: F401

# Explicit re-exports keep existing URL and import references stable.
from .library_transfer_views import (
    open_transfer_candidate,  # noqa: F401
    open_transfer_target,  # noqa: F401
    search_transfer_item,  # noqa: F401
    select_transfer_candidate,  # noqa: F401
    skip_transfer_item,  # noqa: F401
    transfer_library_playlist,  # noqa: F401
    transfer_review,  # noqa: F401
)

logger = logging.getLogger(__name__)


def _safe_optional_url(value):
    value = (value or "").strip()
    if value:
        URLValidator(schemes=["http", "https"])(value)
    return value


@require_POST
def create_playlist(request):
    title = (request.POST.get("title") or "").strip()
    provider = request.POST.get("provider", LibraryPlaylist.Provider.MANUAL)
    description = (request.POST.get("description") or "").strip()
    try:
        external_url = _safe_optional_url(request.POST.get("external_url"))
    except ValidationError:
        messages.error(request, "Ссылка должна быть корректным HTTP(S)-адресом.")
        return redirect("library")
    if not title or len(title) > 120 or len(description) > 240:
        messages.error(request, "Укажи название плейлиста (до 120 символов).")
        return redirect("library")
    if provider not in LibraryPlaylist.Provider.values:
        messages.error(request, "Неизвестный музыкальный сервис.")
        return redirect("library")
    LibraryPlaylist.objects.create(
        profile=_profile(request), title=title, provider=provider,
        description=description, external_url=external_url,
    )
    messages.success(request, "Плейлист добавлен в библиотеку.")
    return redirect("library")


@require_POST
def add_track(request, playlist_id):
    profile = _profile(request)
    playlist = get_object_or_404(LibraryPlaylist, pk=playlist_id, profile=profile)
    title = (request.POST.get("title") or "").strip()
    artist = (request.POST.get("artist") or "").strip()
    album = (request.POST.get("album") or "").strip()
    external_id = (request.POST.get("external_id") or "").strip()
    try:
        external_url = _safe_optional_url(request.POST.get("external_url"))
        raw_duration = (request.POST.get("duration_seconds") or "").strip()
        duration_ms = int(float(raw_duration) * 1000) if raw_duration else None
    except (ValidationError, ValueError, OverflowError):
        messages.error(request, "Проверь ссылку и длительность композиции.")
        return redirect("library")
    if not title or not artist or len(title) > 180 or len(artist) > 180 or len(album) > 180:
        messages.error(request, "Название и исполнитель обязательны (до 180 символов).")
        return redirect("library")
    if duration_ms is not None and not 0 < duration_ms <= 86_400_000:
        messages.error(request, "Длительность должна быть от 1 секунды до 24 часов.")
        return redirect("library")
    if len(external_id) > 200:
        messages.error(request, "Внешний ID слишком длинный.")
        return redirect("library")
    LibraryTrack.objects.create(
        playlist=playlist, title=title, artist=artist, album=album,
        duration_ms=duration_ms, external_id=external_id,
        external_url=external_url, position=playlist.tracks.count(),
    )
    playlist.save(update_fields=["updated_at"])
    messages.success(request, "Композиция добавлена.")
    return redirect("library")


@require_POST
def delete_track(request, track_id):
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist__profile"),
        pk=track_id, playlist__profile=_profile(request),
    )
    track.delete()
    messages.success(request, "Композиция удалена.")
    return redirect("library")


@require_POST
def delete_playlist(request, playlist_id):
    playlist = get_object_or_404(
        LibraryPlaylist, pk=playlist_id, profile=_profile(request),
    )
    playlist.delete()
    messages.success(request, "Плейлист и его локальные записи удалены.")
    return redirect("library")



def _normalized_track_key(artist, title):
    import unicodedata

    value = unicodedata.normalize("NFKD", f"{artist} {title}".casefold().replace("ё", "е"))
    return re.sub(r"[^a-z0-9а-я]+", " ", value).strip()


@require_POST
def merge_playlists(request):
    profile = _profile(request)
    playlist_ids = list(dict.fromkeys(request.POST.getlist("playlist_ids")))
    title = (request.POST.get("title") or "").strip()
    if len(playlist_ids) < 2:
        messages.error(request, "Выбери минимум два плейлиста для объединения.")
        return redirect("library")
    if len(playlist_ids) > 30:
        messages.error(request, "За один раз можно объединить не более 30 плейлистов.")
        return redirect("library")
    if not title or len(title) > 120:
        messages.error(request, "Укажи название новой коллекции (до 120 символов).")
        return redirect("library")

    owned = {
        str(item.pk): item
        for item in LibraryPlaylist.objects.filter(profile=profile, pk__in=playlist_ids)
    }
    if len(owned) != len(playlist_ids):
        messages.error(request, "Один из выбранных плейлистов не найден.")
        return redirect("library")

    ordered_sources = [owned[item_id] for item_id in playlist_ids]
    seen, merged_rows = set(), []
    with transaction.atomic():
        merged = LibraryPlaylist.objects.create(
            profile=profile, title=title,
            provider=LibraryPlaylist.Provider.MANUAL,
            description=f"Объединено из {len(ordered_sources)} плейлистов",
        )
        for source in ordered_sources:
            for track in source.tracks.all().order_by("position", "created_at"):
                key = _normalized_track_key(track.artist, track.title)
                if key in seen:
                    continue
                seen.add(key)
                merged_rows.append(LibraryTrack(
                    playlist=merged, title=track.title, artist=track.artist,
                    album=track.album, duration_ms=track.duration_ms,
                    cover_url=track.cover_url, external_id=track.external_id,
                    external_url=track.external_url,
                    source_provider=track.source_provider or source.provider,
                    audio_file=track.audio_file,
                    position=len(merged_rows),
                ))
        if not merged_rows:
            merged.delete()
            messages.error(request, "В выбранных плейлистах нет композиций для объединения.")
            return redirect("library")
        LibraryTrack.objects.bulk_create(merged_rows)
    messages.success(request, f"Создана коллекция «{merged.title}»: {len(merged_rows)} уникальных композиций.")
    return redirect("playlist_detail", playlist_id=merged.pk)


@require_POST
@login_required
def upload_local_track(request):
    title = (request.POST.get("title") or "").strip()
    artist = (request.POST.get("artist") or "").strip()
    uploaded = request.FILES.get("audio_file")
    allowed = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
    if not title or len(title) > 180 or not artist or len(artist) > 180 or not uploaded:
        messages.error(request, "Укажи название, исполнителя и аудиофайл.")
        return redirect("library")
    suffix = Path(uploaded.name).suffix.lower()
    if suffix not in allowed or uploaded.size > 100 * 1024 * 1024:
        messages.error(request, "Поддерживаются MP3, WAV, OGG, FLAC и M4A размером до 100 МБ.")
        return redirect("library")
    header = uploaded.read(16)
    uploaded.seek(0)
    signatures = {
        ".wav": header.startswith(b"RIFF") and header[8:12] == b"WAVE",
        ".ogg": header.startswith(b"OggS"),
        ".flac": header.startswith(b"fLaC"),
        ".m4a": header[4:8] == b"ftyp",
        ".mp3": header.startswith(b"ID3") or (
            len(header) > 1 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
        ),
    }
    if not signatures.get(suffix, False):
        messages.error(request, "Содержимое файла не соответствует заявленному аудиоформату.")
        return redirect("library")
    profile = _profile(request)
    playlist, _ = LibraryPlaylist.objects.get_or_create(
        profile=profile, title="Мои аудиофайлы",
        defaults={
            "provider": LibraryPlaylist.Provider.MANUAL,
            "description": "Личные аудиофайлы, загруженные в Playlist Bridge",
        },
    )
    track = LibraryTrack.objects.create(
        playlist=playlist, title=title, artist=artist,
        source_provider=LibraryPlaylist.Provider.MANUAL,
        audio_file=uploaded, position=playlist.tracks.count(),
    )
    playlist.save(update_fields=["updated_at"])
    messages.success(request, f"Файл «{track.title}» добавлен в локальную библиотеку.")
    return redirect("playlist_detail", playlist_id=playlist.pk)


@require_POST
def update_profile(request):
    profile = _profile(request)
    display_name = (request.POST.get("display_name") or "").strip()
    if not display_name or len(display_name) > 60:
        messages.error(request, "Имя профиля должно содержать от 1 до 60 символов.")
    else:
        profile.display_name = display_name
        profile.save(update_fields=["display_name", "updated_at"])
        messages.success(request, "Профиль обновлён.")
    return redirect("library")



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



