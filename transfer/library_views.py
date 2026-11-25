# ruff: noqa: I001
import json
import logging
import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse, StreamingHttpResponse
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .services import (
    SoundCloudClient,
    SpotifyClient,
    TransferError,
    VKClient,
    parse_vk_playlist_url,
    parse_vk_track_url,
)
from .models import LibraryPlaylist, LibraryTrack

from .library_support import _profile, _soundcloud_access, _spotify_access

logger = logging.getLogger(__name__)


def _safe_optional_url(value):
    value = (value or "").strip()
    if value:
        URLValidator(schemes=["http", "https"])(value)
    return value


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


@require_POST
def import_vk_playlist(request):
    source_url = (request.POST.get("source_url") or "").strip()
    try:
        owner_id, playlist_id, access_key = parse_vk_playlist_url(source_url)
        logger.info("VK public playlist import started owner_id=%s playlist_id=%s has_access_key=%s", owner_id, playlist_id, bool(access_key))
        api = VKClient(version=settings.VK_API_VERSION)
        title, tracks = api.fetch_playlist(source_url)
        if not tracks:
            raise TransferError("VK не вернул композиции для импорта.")
        profile = _profile(request)
        with transaction.atomic():
            playlist = LibraryPlaylist.objects.create(
                profile=profile, title=title[:120] or "Импорт из VK",
                provider=LibraryPlaylist.Provider.VK, external_url=source_url,
                description=f"Импортировано из VK · {len(tracks)} композиций",
            )
            LibraryTrack.objects.bulk_create([
                LibraryTrack(
                    playlist=playlist, title=track.title[:180], artist=track.artist[:180],
                    duration_ms=max(track.duration, 0) * 1000,
                    cover_url=track.cover_url,
                    external_id=track.audio_id or f"{track.owner_id}_{track.track_id}",
                    external_url=f"https://vk.ru/audio{track.owner_id}_{track.track_id}",
                    source_provider=LibraryPlaylist.Provider.VK,
                    position=index,
                )
                for index, track in enumerate(tracks)
            ])
    except (ValueError, TransferError) as exc:
        logger.warning("VK public playlist import rejected: %s", str(exc)[:240])
        messages.error(request, str(exc) if isinstance(exc, TransferError) else "Укажи корректную ссылку на публичный плейлист VK.")
        return redirect("library")
    except Exception:
        logger.exception("Unexpected error during VK public playlist import")
        messages.error(request, "Не удалось импортировать плейлист VK. Подробности записаны в журнал.")
        return redirect("library")
    logger.info("VK public playlist import completed playlist_id=%s track_count=%s", playlist.pk, len(tracks))
    messages.success(request, f"Импортировано «{playlist.title}»: {len(tracks)} композиций.")
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

def _validate_soundcloud_permalink(value):
    from urllib.parse import urlparse

    parsed = urlparse((value or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in {
        "soundcloud.com", "www.soundcloud.com", "m.soundcloud.com",
    } or parsed.port not in (None, 443) or not parsed.path or parsed.username or parsed.password:
        raise ValueError("Укажи публичную HTTPS-ссылку на soundcloud.com.")
    return parsed.geturl()


def _save_soundcloud_playlist(profile, resource, tracks, source_url):
    title = str(resource.get("title") or "SoundCloud playlist")[:120]
    playlist = LibraryPlaylist.objects.create(
        profile=profile,
        title=title,
        provider=LibraryPlaylist.Provider.SOUNDCLOUD,
        external_url=source_url,
        description=f"Импортировано из SoundCloud · {len(tracks)} композиций",
    )
    rows = []
    for index, item in enumerate(tracks):
        if not isinstance(item, dict) or not item.get("id") or not item.get("title"):
            continue
        user = item.get("user")
        if not isinstance(user, dict):
            user = {}
        try:
            raw_duration = item.get("duration")
            if isinstance(raw_duration, bool):
                raise TypeError("Boolean duration is invalid.")
            parsed_duration = max(0, int(raw_duration or 0))
            duration_ms = parsed_duration if parsed_duration <= 2_147_483_647 else None
        except (TypeError, ValueError, OverflowError):
            # A malformed duration must not leave an empty playlist behind or
            # discard otherwise usable track metadata.
            duration_ms = None
        rows.append(LibraryTrack(
            playlist=playlist,
            title=str(item.get("title") or "Unknown track")[:180],
            artist=str(item.get("metadata_artist") or user.get("username") or "Unknown artist")[:180],
            duration_ms=duration_ms,
            external_id=str(item.get("id"))[:200],
            external_url=str(item.get("permalink_url") or "")[:2048],
            position=index,
        ))
    if not rows:
        playlist.delete()
        raise TransferError("SoundCloud не вернул доступные композиции.")
    LibraryTrack.objects.bulk_create(rows)
    return playlist, len(rows)


@require_POST
def import_soundcloud_playlist(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        source_url = _validate_soundcloud_permalink(source_url)
        client, token = _soundcloud_access(request)
        resource = client.resolve(token, source_url)
        if resource.get("kind") != "playlist" and "tracks" not in resource:
            raise TransferError("Ссылка ведёт не на плейлист SoundCloud.")
        resource_id = resource.get("id")
        tracks = client.playlist_tracks(token, resource_id) if resource_id else resource.get("tracks", [])
        playlist, count = _save_soundcloud_playlist(_profile(request), resource, tracks, source_url)
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Импортирован плейлист «{playlist.title}»: {count} композиций.")
    return redirect("library")


@require_POST
def import_soundcloud_track(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        source_url = _validate_soundcloud_permalink(source_url)
        client, token = _soundcloud_access(request)
        resource = client.resolve(token, source_url)
        if resource.get("kind") != "track" and "duration" not in resource:
            raise TransferError("Ссылка ведёт не на трек SoundCloud.")
        profile = _profile(request)
        playlist, _count = _save_soundcloud_playlist(
            profile,
            {"title": f"SoundCloud — {resource.get('title') or 'Track'}"},
            [resource],
            source_url,
        )
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Композиция добавлена в библиотеку: {playlist.title}.")
    return redirect("library")


@require_POST
def import_soundcloud_library(request):
    try:
        client, token = _soundcloud_access(request)
        resources = client.my_playlists(token)
        profile = _profile(request)
        imported = 0
        track_count = 0
        for resource in resources[:30]:
            resource_id = resource.get("id")
            if not resource_id:
                continue
            tracks = client.playlist_tracks(token, resource_id)
            source_url = resource.get("permalink_url") or ""
            if source_url:
                _save_soundcloud_playlist(profile, resource, tracks, source_url)
                imported += 1
                track_count += len(tracks)
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Импортировано плейлистов: {imported}; композиций: {track_count}.")
    return redirect("library")


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


def _spotify_resource_id(value, resource_type):
    from urllib.parse import urlparse

    value = (value or "").strip()
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Укажи ссылку на Spotify.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"open.spotify.com", "www.open.spotify.com"}
        or port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Укажи ссылку на Spotify.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[-2] != resource_type or not re.fullmatch(r"[A-Za-z0-9]{22}", parts[-1]):
        raise ValueError("Ссылка Spotify имеет неверный формат.")
    return parts[-1]


def _save_spotify_playlist(profile, resource, entries, source_url):
    playlist = LibraryPlaylist.objects.create(
        profile=profile,
        title=str(resource.get("name") or "Spotify playlist")[:120],
        provider=LibraryPlaylist.Provider.SPOTIFY,
        external_url=source_url,
        description="Импортировано из Spotify",
    )
    rows = []
    for index, entry in enumerate(entries):
        track = entry.get("item") or entry.get("track") or {}
        if track.get("type") not in (None, "track") or not track.get("id"):
            continue
        artists = track.get("artists") or []
        artist = ", ".join(str(item.get("name") or "") for item in artists if item.get("name"))
        album = (track.get("album") or {}).get("name") or ""
        external_url = (track.get("external_urls") or {}).get("spotify", "")
        rows.append(LibraryTrack(
            playlist=playlist,
            title=str(track.get("name") or "Unknown track")[:180],
            artist=artist[:180] or "Unknown artist",
            album=str(album)[:180],
            duration_ms=track.get("duration_ms"),
            external_id=str(track.get("id"))[:200],
            external_url=str(external_url)[:2048],
            position=index,
        ))
    if not rows:
        playlist.delete()
        raise TransferError("Spotify не вернул доступные композиции этого плейлиста.")
    LibraryTrack.objects.bulk_create(rows)
    return playlist, len(rows)


@require_POST
def import_spotify_playlist(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        playlist_id = _spotify_resource_id(source_url, "playlist")
        client, token = _spotify_access(request)
        resource = client.api("playlist_details", token, playlist_id=playlist_id)
        entries = client.get_playlist_items(token, playlist_id)
        playlist, count = _save_spotify_playlist(_profile(request), resource, entries, source_url)
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Импортирован Spotify-плейлист «{playlist.title}»: {count} композиций.")
    return redirect("library")


@require_POST
def import_spotify_track(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        track_id = _spotify_resource_id(source_url, "track")
        client, token = _spotify_access(request)
        track = client.track_details(token, track_id)
        resource = {"name": f"Spotify — {track.get('name') or 'Track'}"}
        playlist, _count = _save_spotify_playlist(
            _profile(request), resource, [{"item": track}], source_url,
        )
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Трек добавлен в библиотеку: {playlist.title}.")
    return redirect("library")


@require_POST
def import_spotify_library(request):
    try:
        client, token = _spotify_access(request)
        resources = client.my_playlists(token)
        profile = _profile(request)
        imported = 0
        track_count = 0
        skipped = 0
        for resource in resources[:30]:
            playlist_id = resource.get("id")
            if not playlist_id:
                continue
            try:
                entries = client.get_playlist_items(token, playlist_id)
                count = len(entries)
                if count:
                    _save_spotify_playlist(
                        profile,
                        resource,
                        entries,
                        (resource.get("external_urls") or {}).get("spotify", ""),
                    )
                    imported += 1
                    track_count += count
            except TransferError:
                skipped += 1
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(
        request,
        f"Spotify: импортировано плейлистов {imported}, композиций {track_count}; пропущено недоступных плейлистов: {skipped}.",
    )
    return redirect("library")




@require_POST
def import_vk_track(request):
    source_url = (request.POST.get("source_url") or "").strip()
    try:
        parse_vk_track_url(source_url)
        track = VKClient(version=settings.VK_API_VERSION).fetch_track(source_url)
        playlist = LibraryPlaylist.objects.create(
            profile=_profile(request), title=f"VK — {track.artist} — {track.title}"[:120],
            provider=LibraryPlaylist.Provider.VK, external_url=source_url,
            description="Импортирована отдельная аудиозапись VK",
        )
        LibraryTrack.objects.create(
            playlist=playlist, title=track.title[:180], artist=track.artist[:180],
            duration_ms=max(0, track.duration) * 1000,
            cover_url=track.cover_url,
            external_id=track.audio_id or f"{track.owner_id}_{track.track_id}",
            external_url=source_url, source_provider=LibraryPlaylist.Provider.VK, position=0,
        )
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    except Exception:
        logger.exception("Unexpected error during VK track import")
        messages.error(request, "Не удалось импортировать трек VK.")
        return redirect("library")
    messages.success(request, f"Трек «{track.title}» добавлен в библиотеку.")
    return redirect("library")


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


@login_required
@require_POST
def refresh_vk_artwork(request, playlist_id):
    playlist = get_object_or_404(LibraryPlaylist, pk=playlist_id, profile=_profile(request))
    if playlist.provider != LibraryPlaylist.Provider.VK:
        messages.error(request, "Обновление обложек доступно только для плейлистов VK.")
        return redirect("playlist_detail", playlist_id=playlist.pk)
    try:
        _title, vk_tracks = VKClient(version=settings.VK_API_VERSION).fetch_playlist(playlist.external_url)
        indexed = {f"{item.owner_id}_{item.track_id}": item for item in vk_tracks}
        updated = 0
        for track in playlist.tracks.all():
            base_id = "_".join(track.external_id.split("_")[:2])
            source = indexed.get(base_id)
            if not source:
                continue
            changed = []
            if source.cover_url and track.cover_url != source.cover_url:
                track.cover_url = source.cover_url
                changed.append("cover_url")
            if source.audio_id and track.external_id != source.audio_id:
                track.external_id = source.audio_id
                changed.append("external_id")
            if track.source_provider != LibraryPlaylist.Provider.VK:
                track.source_provider = LibraryPlaylist.Provider.VK
                changed.append("source_provider")
            if changed:
                track.save(update_fields=changed)
                updated += 1
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("playlist_detail", playlist_id=playlist.pk)
    messages.success(request, f"Обновлены данные {updated} композиций. Обложки появятся там, где VK их предоставляет.")
    return redirect("playlist_detail", playlist_id=playlist.pk)


# Backward-compatible exports; URL configuration and external imports remain stable.
from .library_transfer_views import (
    open_transfer_candidate,
    open_transfer_target,
    search_transfer_item,
    select_transfer_candidate,
    skip_transfer_item,
    transfer_library_playlist,
    transfer_review,
)
