"""Local library management endpoints."""

from pathlib import Path

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .library_support import _profile
from .models import LibraryPlaylist, LibraryTrack


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
