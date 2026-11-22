from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .credentials import get_session_fingerprint
from .models import LibraryPlaylist, LibraryProfile, LibraryTrack


def _profile(request):
    fingerprint = get_session_fingerprint(request)
    profile, _ = LibraryProfile.objects.get_or_create(session_fingerprint=fingerprint)
    return profile


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
        return redirect("home")
    if not title or len(title) > 120 or len(description) > 240:
        messages.error(request, "Укажи название плейлиста (до 120 символов).")
        return redirect("home")
    if provider not in LibraryPlaylist.Provider.values:
        messages.error(request, "Неизвестный музыкальный сервис.")
        return redirect("home")
    LibraryPlaylist.objects.create(
        profile=_profile(request), title=title, provider=provider,
        description=description, external_url=external_url,
    )
    messages.success(request, "Плейлист добавлен в библиотеку.")
    return redirect("home")


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
        return redirect("home")
    if not title or not artist or len(title) > 180 or len(artist) > 180 or len(album) > 180:
        messages.error(request, "Название и исполнитель обязательны (до 180 символов).")
        return redirect("home")
    if duration_ms is not None and not 0 < duration_ms <= 86_400_000:
        messages.error(request, "Длительность должна быть от 1 секунды до 24 часов.")
        return redirect("home")
    if len(external_id) > 200:
        messages.error(request, "Внешний ID слишком длинный.")
        return redirect("home")
    LibraryTrack.objects.create(
        playlist=playlist, title=title, artist=artist, album=album,
        duration_ms=duration_ms, external_id=external_id,
        external_url=external_url, position=playlist.tracks.count(),
    )
    playlist.save(update_fields=["updated_at"])
    messages.success(request, "Композиция добавлена.")
    return redirect("home")


@require_POST
def delete_track(request, track_id):
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist__profile"),
        pk=track_id, playlist__profile=_profile(request),
    )
    track.delete()
    messages.success(request, "Композиция удалена.")
    return redirect("home")


@require_POST
def delete_playlist(request, playlist_id):
    playlist = get_object_or_404(
        LibraryPlaylist, pk=playlist_id, profile=_profile(request),
    )
    playlist.delete()
    messages.success(request, "Плейлист и его локальные записи удалены.")
    return redirect("home")



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
    return redirect("home")


@require_POST
def import_vk_playlist(request):
    from django.conf import settings
    from django.db import transaction

    from .core import VKClient, TransferError
    from .credentials import get_access_token
    from .views import vk_client

    source_url = (request.POST.get("source_url") or "").strip()
    try:
        from .core import parse_vk_playlist_url
        parse_vk_playlist_url(source_url)
        fingerprint = get_session_fingerprint(request)
        oauth_client = vk_client()
        access_token, _ = get_access_token(fingerprint, "vk", oauth_client)
        api = VKClient(access_token, settings.VK_API_VERSION, settings.VK_ID_CLIENT_ID)
        title, tracks = api.fetch_playlist(source_url)
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc) if isinstance(exc, TransferError) else "Укажи корректную ссылку на плейлист VK.")
        return redirect("home")
    if not tracks:
        messages.error(request, "VK не вернул композиции для импорта.")
        return redirect("home")

    profile = _profile(request)
    playlist = LibraryPlaylist.objects.create(
        profile=profile,
        title=title[:120] or "Импорт из VK",
        provider=LibraryPlaylist.Provider.VK,
        external_url=source_url,
        description=f"Импортировано из VK · {len(tracks)} композиций",
    )
    LibraryTrack.objects.bulk_create([
        LibraryTrack(
            playlist=playlist,
            title=track.title[:180],
            artist=track.artist[:180],
            duration_ms=max(track.duration, 0) * 1000,
            external_id=f"{track.owner_id}_{track.track_id}",
            external_url="",
            position=index,
        )
        for index, track in enumerate(tracks)
    ])
    messages.success(request, f"Импортировано «{playlist.title}»: {len(tracks)} композиций.")
    return redirect("home")


@require_GET
def open_playlist_source(request, playlist_id):
    from django.core.exceptions import ValidationError
    from django.core.validators import URLValidator
    from django.http import HttpResponseRedirect

    playlist = get_object_or_404(
        LibraryPlaylist, pk=playlist_id, profile=_profile(request)
    )
    try:
        URLValidator(schemes=["http", "https"])(playlist.external_url)
    except ValidationError:
        return redirect("home")
    return HttpResponseRedirect(playlist.external_url)


@require_GET
def open_track_source(request, track_id):
    from django.core.exceptions import ValidationError
    from django.core.validators import URLValidator
    from django.http import HttpResponseRedirect

    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist__profile"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    try:
        URLValidator(schemes=["http", "https"])(track.external_url)
    except ValidationError:
        return redirect("home")
    return HttpResponseRedirect(track.external_url)
