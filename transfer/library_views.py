import re
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from .core import (
    SoundCloudClient,
    SpotifyClient,
    TransferError,
    VKClient,
    VKIDClient,
    parse_vk_playlist_url,
    parse_vk_track_url,
    score_candidate,
)
from .credentials import get_access_token, get_session_fingerprint
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

    source_url = (request.POST.get("source_url") or "").strip()
    try:
        parse_vk_playlist_url(source_url)
        fingerprint = get_session_fingerprint(request)
        if not settings.VK_ID_CLIENT_ID:
            raise TransferError("VK ID OAuth не настроен на сервере.")
        oauth_client = VKIDClient(settings.VK_ID_CLIENT_ID, settings.VK_ID_REDIRECT_URI, settings.VK_ID_SERVICE_TOKEN)
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
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts.get(playlist.provider, set()):
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
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts.get(provider, set()):
        return redirect("home")
    return HttpResponseRedirect(track.external_url)


def _soundcloud_access(request):
    client = SoundCloudClient(
        settings.SOUNDCLOUD_CLIENT_ID,
        settings.SOUNDCLOUD_CLIENT_SECRET,
        settings.SOUNDCLOUD_REDIRECT_URI,
    )
    token, _ = get_access_token(get_session_fingerprint(request), "soundcloud", client)
    return client, token


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
        user = item.get("user") or {}
        rows.append(LibraryTrack(
            playlist=playlist,
            title=str(item.get("title") or "Unknown track")[:180],
            artist=str(item.get("metadata_artist") or user.get("username") or "Unknown artist")[:180],
            duration_ms=max(0, int(item.get("duration") or 0)),
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
        return redirect("home")
    messages.success(request, f"Импортирован плейлист «{playlist.title}»: {count} композиций.")
    return redirect("home")


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
        return redirect("home")
    messages.success(request, f"Композиция добавлена в библиотеку: {playlist.title}.")
    return redirect("home")


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
        return redirect("home")
    messages.success(request, f"Импортировано плейлистов: {imported}; композиций: {track_count}.")
    return redirect("home")


@require_POST
def transfer_library_playlist(request, playlist_id):
    from types import SimpleNamespace

    playlist = get_object_or_404(
        LibraryPlaylist.objects.prefetch_related("tracks"),
        pk=playlist_id,
        profile=_profile(request),
    )
    target = request.POST.get("target_provider", "").strip()
    if target not in {"spotify", "soundcloud"}:
        messages.error(request, "Выбери поддерживаемый целевой сервис.")
        return redirect("home")
    tracks = list(playlist.tracks.all())
    if not tracks:
        messages.error(request, "В плейлисте нет композиций для переноса.")
        return redirect("home")
    if len(tracks) > 100:
        messages.error(request, "Пока можно переносить не более 100 композиций за один запуск.")
        return redirect("home")

    fingerprint = get_session_fingerprint(request)
    matched_ids = []
    matched_tracks = []
    not_found = 0
    try:
        if target == "spotify":
            client = SpotifyClient(
                settings.SPOTIFY_CLIENT_ID,
                settings.SPOTIFY_CLIENT_SECRET,
                settings.SPOTIFY_REDIRECT_URI,
            )
            token, _ = get_access_token(fingerprint, "spotify", client)
            for track in tracks:
                source = SimpleNamespace(
                    title=track.title,
                    artist=track.artist,
                    duration=(track.duration_ms or 0) // 1000,
                )
                ranked = sorted(
                    ((score_candidate(source, item), item) for item in client.search(token, track.artist, track.title)),
                    key=lambda pair: pair[0],
                    reverse=True,
                )
                if ranked and ranked[0][0] >= 0.82 and ranked[0][1].get("uri"):
                    matched_ids.append(ranked[0][1]["uri"])
                    matched_tracks.append((track, ranked[0][1].get("id", ""), (ranked[0][1].get("external_urls") or {}).get("spotify", "")))
                else:
                    not_found += 1
            if not matched_ids:
                raise TransferError("Не удалось подобрать композиции в Spotify.")
            target_id = client.create_playlist(token, playlist.title)
            client.add_items(token, target_id, matched_ids)
            target_url = f"https://open.spotify.com/playlist/{target_id}"
        else:
            client = SoundCloudClient(
                settings.SOUNDCLOUD_CLIENT_ID,
                settings.SOUNDCLOUD_CLIENT_SECRET,
                settings.SOUNDCLOUD_REDIRECT_URI,
            )
            token, _ = get_access_token(fingerprint, "soundcloud", client)
            for track in tracks:
                query = f"{track.artist} {track.title}"
                candidates = client.search_tracks(token, query)
                ranked = []
                for candidate in candidates:
                    user = candidate.get("user") or {}
                    normalized = {
                        "name": candidate.get("title", ""),
                        "artists": [{"name": candidate.get("metadata_artist") or user.get("username", "")}],
                        "duration_ms": candidate.get("duration"),
                    }
                    source = SimpleNamespace(
                        title=track.title,
                        artist=track.artist,
                        duration=(track.duration_ms or 0) // 1000,
                    )
                    ranked.append((score_candidate(source, normalized), candidate))
                ranked.sort(key=lambda pair: pair[0], reverse=True)
                if ranked and ranked[0][0] >= 0.82 and ranked[0][1].get("id"):
                    matched_ids.append(str(ranked[0][1]["id"]))
                    matched_tracks.append((track, str(ranked[0][1]["id"]), str(ranked[0][1].get("permalink_url") or "")))
                else:
                    not_found += 1
            if not matched_ids:
                raise TransferError("Не удалось подобрать композиции в SoundCloud.")
            result = client.create_playlist(token, playlist.title, matched_ids)
            target_id = str(result["id"])
            target_url = result.get("permalink_url") or "https://soundcloud.com"
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("home")

    target_playlist = LibraryPlaylist.objects.create(
        profile=playlist.profile,
        title=f"{playlist.title} · {target.title()}",
        provider=target,
        external_url=target_url,
        description=f"Создано переносом из библиотеки · найдено {len(matched_ids)} из {len(tracks)}",
    )
    LibraryTrack.objects.bulk_create([
        LibraryTrack(
            playlist=target_playlist,
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_ms=track.duration_ms,
            external_id=external_id,
            external_url=external_url,
            position=index,
        )
        for index, (track, external_id, external_url) in enumerate(matched_tracks)
    ])
    messages.success(
        request,
        f"Создан плейлист {target.title()}: найдено {len(matched_ids)} из {len(tracks)} треков. "
        f"Не найдено: {not_found}. {target_url}",
    )
    return redirect("home")


@require_POST
def upload_track_to_soundcloud(request):
    uploaded = request.FILES.get("audio_file")
    title = (request.POST.get("title") or "").strip()
    artist = (request.POST.get("artist") or "").strip()
    description = (request.POST.get("description") or "").strip()
    allowed_extensions = {".mp3", ".wav", ".flac", ".aiff", ".aif", ".ogg", ".aac", ".amr", ".wma", ".mp2"}
    if not uploaded or not title or not artist or len(title) > 100 or len(artist) > 100:
        messages.error(request, "Выбери аудиофайл и укажи название и исполнителя.")
        return redirect("home")
    if Path(uploaded.name).suffix.lower() not in allowed_extensions or uploaded.size > 100 * 1024 * 1024:
        messages.error(request, "Поддерживаются аудиофайлы до 100 МБ в форматах MP3, WAV, FLAC, AIFF, OGG, AAC, AMR, WMA и MP2.")
        return redirect("home")
    try:
        client, token = _soundcloud_access(request)
        result = client.upload_track(token, uploaded, title, artist, description)
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("home")

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
    return redirect("home")


def _spotify_access(request):
    client = SpotifyClient(
        settings.SPOTIFY_CLIENT_ID,
        settings.SPOTIFY_CLIENT_SECRET,
        settings.SPOTIFY_REDIRECT_URI,
    )
    token, _ = get_access_token(get_session_fingerprint(request), "spotify", client)
    return client, token


def _spotify_resource_id(value, resource_type):
    from urllib.parse import urlparse

    value = (value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"open.spotify.com", "www.open.spotify.com"}:
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
        return redirect("home")
    messages.success(request, f"Импортирован Spotify-плейлист «{playlist.title}»: {count} композиций.")
    return redirect("home")


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
        return redirect("home")
    messages.success(request, f"Трек добавлен в библиотеку: {playlist.title}.")
    return redirect("home")


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
        return redirect("home")
    messages.success(
        request,
        f"Spotify: импортировано плейлистов {imported}, композиций {track_count}; пропущено недоступных плейлистов: {skipped}.",
    )
    return redirect("home")




@require_POST
def import_vk_track(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        parse_vk_track_url(source_url)
        if not settings.VK_ID_CLIENT_ID:
            raise TransferError("VK ID OAuth не настроен на сервере.")
        client = VKIDClient(settings.VK_ID_CLIENT_ID, settings.VK_ID_REDIRECT_URI, settings.VK_ID_SERVICE_TOKEN)
        token, _ = get_access_token(get_session_fingerprint(request), "vk", client)
        track = VKClient(token, settings.VK_API_VERSION, settings.VK_ID_CLIENT_ID).fetch_track(source_url)
        playlist = LibraryPlaylist.objects.create(
            profile=_profile(request),
            title=f"VK — {track.artist} — {track.title}"[:120],
            provider=LibraryPlaylist.Provider.VK,
            external_url=source_url,
            description="Импортирована отдельная аудиозапись VK",
        )
        LibraryTrack.objects.create(
            playlist=playlist, title=track.title[:180], artist=track.artist[:180],
            duration_ms=max(0, track.duration) * 1000,
            external_id=f"{track.owner_id}_{track.track_id}",
            external_url=source_url, position=0,
        )
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("home")
    messages.success(request, f"Трек «{track.title}» добавлен в библиотеку.")
    return redirect("home")
