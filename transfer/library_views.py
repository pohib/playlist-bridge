import logging
import re
from pathlib import Path

from django.conf import settings
from django.db import transaction
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
from .models import LibraryPlaylist, LibraryProfile, LibraryTrack, LibraryTransfer, LibraryTransferItem

logger = logging.getLogger(__name__)


def _profile(request):
    fingerprint = get_session_fingerprint(request)
    if getattr(request, "user", None) is not None and request.user.is_authenticated:
        profile = LibraryProfile.objects.filter(session_fingerprint=fingerprint).first()
        if profile:
            if profile.user_id != request.user.pk:
                profile.user = request.user
                profile.save(update_fields=["user"])
            return profile
        profile, _ = LibraryProfile.objects.get_or_create(
            user=request.user,
            defaults={"session_fingerprint": fingerprint},
        )
        return profile
    profile, _ = LibraryProfile.objects.get_or_create(session_fingerprint=fingerprint)
    return profile


def _safe_optional_url(value):
    value = (value or "").strip()
    if value:
        URLValidator(schemes=["http", "https"])(value)
    return value


def _safe_candidate_url(value, provider):
    from urllib.parse import urlparse

    parsed = urlparse((value or "").strip())
    try:
        port = parsed.port
    except ValueError:
        return ""
    allowed_hosts = {
        "spotify": {"open.spotify.com", "www.open.spotify.com"},
        "soundcloud": {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"},
    }
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts.get(provider, set())
        or port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        return ""
    return parsed.geturl()


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
        return redirect("library")
    if not tracks:
        messages.error(request, "VK не вернул композиции для импорта.")
        return redirect("library")

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
            external_url=f"https://vk.com/audio{track.owner_id}_{track.track_id}",
            position=index,
        )
        for index, track in enumerate(tracks)
    ])
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
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts.get(playlist.provider, set()):
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
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts.get(provider, set()):
        return redirect("library")
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


@require_POST
def transfer_library_playlist(request, playlist_id):
    from types import SimpleNamespace
    from django.utils import timezone

    playlist = get_object_or_404(
        LibraryPlaylist.objects.prefetch_related("tracks"),
        pk=playlist_id,
        profile=_profile(request),
    )
    target = request.POST.get("target_provider", "").strip()
    if target not in {"spotify", "soundcloud"}:
        messages.error(request, "Выбери поддерживаемый целевой сервис.")
        return redirect("playlist_detail", playlist_id=playlist.pk)
    tracks = list(playlist.tracks.all())
    if not tracks:
        messages.error(request, "В плейлисте нет композиций для переноса.")
        return redirect("playlist_detail", playlist_id=playlist.pk)
    if len(tracks) > 100:
        messages.error(request, "Пока можно переносить не более 100 композиций за один запуск.")
        return redirect("playlist_detail", playlist_id=playlist.pk)

    fingerprint = get_session_fingerprint(request)
    matched = {}
    unmatched = []
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
                if ranked and ranked[0][0] >= 0.82 and re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", str(ranked[0][1].get("uri") or "")):
                    item = ranked[0][1]
                    matched[track.pk] = {
                        "id": str(item.get("id") or ""),
                        "uri": str(item.get("uri") or ""),
                        "url": _safe_candidate_url((item.get("external_urls") or {}).get("spotify", ""), "spotify"),
                    }
                else:
                    unmatched.append((track, [
                        {
                            "id": str(item.get("id") or ""),
                            "uri": str(item.get("uri") or ""),
                            "title": str(item.get("name") or "")[:180],
                            "artist": ", ".join(str(artist.get("name") or "") for artist in item.get("artists", []))[:180],
                            "duration_ms": int(item.get("duration_ms") or 0),
                            "url": _safe_candidate_url((item.get("external_urls") or {}).get("spotify", ""), "spotify"),
                        }
                        for score, item in ranked[:5] if score >= 0.45 and item.get("id") and re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", str(item.get("uri") or ""))
                    ]))
            uris = [
                matched[track.pk]["uri"]
                for track in tracks
                if track.pk in matched and matched[track.pk].get("uri")
            ]
            target_id = client.create_playlist(token, playlist.title) if uris else ""
            if target_id:
                client.add_items(token, target_id, uris)
            target_url = f"https://open.spotify.com/playlist/{target_id}" if target_id else ""
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
                source = SimpleNamespace(
                    title=track.title,
                    artist=track.artist,
                    duration=(track.duration_ms or 0) // 1000,
                )
                for candidate in candidates:
                    user = candidate.get("user") or {}
                    normalized = {
                        "name": candidate.get("title", ""),
                        "artists": [{"name": candidate.get("metadata_artist") or user.get("username", "")}],
                        "duration_ms": candidate.get("duration"),
                    }
                    ranked.append((score_candidate(source, normalized), candidate))
                ranked.sort(key=lambda pair: pair[0], reverse=True)
                if ranked and ranked[0][0] >= 0.82 and re.fullmatch(r"[0-9]+", str(ranked[0][1].get("id") or "")):
                    candidate = ranked[0][1]
                    matched[track.pk] = {
                        "id": str(candidate["id"]),
                        "url": _safe_candidate_url(candidate.get("permalink_url"), "soundcloud"),
                    }
                else:
                    unmatched.append((track, [
                        {
                            "id": str(candidate.get("id") or ""),
                            "uri": str(candidate.get("urn") or candidate.get("id") or ""),
                            "title": str(candidate.get("title") or "")[:180],
                            "artist": str(candidate.get("metadata_artist") or (candidate.get("user") or {}).get("username") or "")[:180],
                            "duration_ms": int(candidate.get("duration") or 0),
                            "url": str(candidate.get("permalink_url") or ""),
                        }
                        for score, candidate in ranked[:5] if score >= 0.45 and re.fullmatch(r"[0-9]+", str(candidate.get("id") or ""))
                    ]))
            target_ids = [matched[track.pk]["id"] for track in tracks if track.pk in matched]
            if target_ids:
                result = client.create_playlist(token, playlist.title, target_ids)
                target_id = str(result["id"])
                target_url = _safe_candidate_url(result.get("permalink_url"), "soundcloud") or "https://soundcloud.com"
            else:
                target_id = ""
                target_url = ""

    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("playlist_detail", playlist_id=playlist.pk)

    target_playlist = LibraryPlaylist.objects.create(
        profile=playlist.profile,
        title=f"{playlist.title} · {target.title()}"[:120],
        provider=target,
        external_url=target_url,
        description=f"Перенос из библиотеки · найдено {len(matched)} из {len(tracks)}",
    )
    LibraryTrack.objects.bulk_create([
        LibraryTrack(
            playlist=target_playlist,
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_ms=track.duration_ms,
            external_id=matched[track.pk]["id"],
            external_url=matched[track.pk]["url"],
            position=index,
        )
        for index, track in enumerate(tracks) if track.pk in matched
    ])

    review = LibraryTransfer.objects.create(
        profile=playlist.profile,
        source_playlist=playlist,
        target_provider=target,
        target_playlist=target_playlist,
        target_playlist_id=str(target_id),
        target_url=target_url,
        status=LibraryTransfer.Status.REVIEW if unmatched else LibraryTransfer.Status.COMPLETED,
        total=len(tracks),
        matched=len(matched),
        completed_at=timezone.now() if not unmatched else None,
    )
    pending_by_id = {track.pk: candidates for track, candidates in unmatched}
    LibraryTransferItem.objects.bulk_create([
        LibraryTransferItem(
            transfer=review,
            source_track=track,
            position=index,
            status=LibraryTransferItem.Status.MATCHED if track.pk in matched else LibraryTransferItem.Status.PENDING,
            candidates=pending_by_id.get(track.pk, []),
            target_external_id=matched.get(track.pk, {}).get("id", ""),
            target_url=matched.get(track.pk, {}).get("url", ""),
        )
        for index, track in enumerate(tracks)
    ])
    logger.info(
        "Library transfer created transfer_id=%s profile_id=%s target=%s total=%s matched=%s pending=%s",
        review.pk, playlist.profile_id, target, len(tracks), len(matched), len(unmatched),
    )
    messages.success(
        request,
        f"Создан плейлист {target.title()}: найдено {len(matched)} из {len(tracks)}. "
        f"Требуют ручного сопоставления: {len(unmatched)}.",
    )
    return redirect("transfer_review", transfer_id=review.pk)


@require_GET
def transfer_review(request, transfer_id):
    review = get_object_or_404(
        LibraryTransfer.objects.prefetch_related("items__source_track"),
        pk=transfer_id,
        profile=_profile(request),
    )
    pending = list(review.items.filter(status=LibraryTransferItem.Status.PENDING).order_by("position"))
    first_pending_id = pending[0].pk if pending else None
    return render(request, "transfer/transfer_review.html", {
        "transfer": review,
        "items": review.items.select_related("source_track").all(),
        "first_pending_id": first_pending_id,
    })


@require_POST
def search_transfer_item(request, transfer_id, item_id):
    review = get_object_or_404(LibraryTransfer, pk=transfer_id, profile=_profile(request))
    item = get_object_or_404(
        LibraryTransferItem.objects.select_related("source_track"),
        pk=item_id, transfer=review, status=LibraryTransferItem.Status.PENDING,
    )
    if review.items.filter(
        status=LibraryTransferItem.Status.PENDING,
        position__lt=item.position,
    ).exists():
        messages.error(request, "Сначала разберись с предыдущими треками, чтобы сохранить порядок.")
        return redirect("transfer_review", transfer_id=review.pk)
    query = (request.POST.get("query") or "").strip()
    if not query or len(query) > 180:
        messages.error(request, "Введи поисковый запрос длиной до 180 символов.")
        return redirect("transfer_review", transfer_id=review.pk)
    try:
        if review.target_provider == "spotify":
            client, token = _spotify_access(request)
            results = client.search_tracks(token, query)
            candidates = [{
                "id": str(result.get("id") or ""),
                "uri": str(result.get("uri") or ""),
                "title": str(result.get("name") or "")[:180],
                "artist": ", ".join(str(artist.get("name") or "") for artist in result.get("artists", []))[:180],
                "duration_ms": int(result.get("duration_ms") or 0),
                "url": _safe_candidate_url((result.get("external_urls") or {}).get("spotify", ""), "spotify"),
            } for result in results if result.get("id") and result.get("uri")]
        else:
            client, token = _soundcloud_access(request)
            results = client.search_tracks(token, query)
            candidates = [{
                "id": str(result.get("id") or ""),
                "uri": str(result.get("urn") or result.get("id") or ""),
                "title": str(result.get("title") or "")[:180],
                "artist": str(result.get("metadata_artist") or (result.get("user") or {}).get("username") or "")[:180],
                "duration_ms": int(result.get("duration") or 0),
                "url": _safe_candidate_url(result.get("permalink_url"), "soundcloud"),
            } for result in results if result.get("id")]
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("transfer_review", transfer_id=review.pk)
    item.candidates = candidates[:10]
    item.save(update_fields=["candidates", "updated_at"])
    messages.success(request, f"Найдено вариантов: {len(item.candidates)}. Выбери правильную композицию.")
    return redirect("transfer_review", transfer_id=review.pk)


@transaction.atomic
@require_POST
def select_transfer_candidate(request, transfer_id, item_id):
    from django.utils import timezone

    review = get_object_or_404(
        LibraryTransfer.objects.select_for_update(),
        pk=transfer_id, profile=_profile(request),
    )
    item = get_object_or_404(
        LibraryTransferItem.objects.select_for_update().select_related("source_track"),
        pk=item_id, transfer=review, status=LibraryTransferItem.Status.PENDING,
    )
    if review.items.filter(
        status=LibraryTransferItem.Status.PENDING,
        position__lt=item.position,
    ).exists():
        messages.error(request, "Сначала сопоставь или пропусти предыдущие треки.")
        return redirect("transfer_review", transfer_id=review.pk)
    candidate_id = (request.POST.get("candidate_id") or "").strip()
    candidate = next((entry for entry in item.candidates if entry.get("id") == candidate_id), None)
    if not candidate:
        messages.error(request, "Выбранный вариант отсутствует в результатах поиска. Выполни поиск повторно.")
        return redirect("transfer_review", transfer_id=review.pk)
    try:
        if review.target_provider == "spotify":
            client, token = _spotify_access(request)
            if not candidate.get("uri"):
                raise TransferError("Spotify не вернул URI выбранной композиции.")
            if not review.target_playlist_id:
                review.target_playlist_id = client.create_playlist(token, review.source_playlist.title)
                review.target_url = f"https://open.spotify.com/playlist/{review.target_playlist_id}"
                client.add_items(token, review.target_playlist_id, [candidate["uri"]])
            else:
                insert_position = review.items.filter(
                    status=LibraryTransferItem.Status.MATCHED,
                    position__lt=item.position,
                ).count()
                client.add_items(token, review.target_playlist_id, [candidate["uri"]], position=insert_position)
        else:
            client, token = _soundcloud_access(request)
            existing = list(
                review.items.filter(status=LibraryTransferItem.Status.MATCHED)
                .exclude(target_external_id="")
                .order_by("position")
                .values_list("position", "target_external_id")
            )
            ordered = sorted(existing + [(item.position, candidate_id)], key=lambda value: value[0])
            ordered_ids = [track_id for _, track_id in ordered]
            if not review.target_playlist_id:
                result = client.create_playlist(token, review.source_playlist.title, ordered_ids)
                review.target_playlist_id = str(result["id"])
                review.target_url = _safe_candidate_url(result.get("permalink_url"), "soundcloud") or "https://soundcloud.com"
            else:
                client.update_playlist_tracks(token, review.target_playlist_id, ordered_ids)
        if review.target_playlist:
            review.target_playlist.external_url = review.target_url
            review.target_playlist.save(update_fields=["external_url", "updated_at"])
        review.save(update_fields=["target_playlist_id", "target_url"])
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("transfer_review", transfer_id=review.pk)

    item.status = LibraryTransferItem.Status.MATCHED
    item.target_external_id = candidate_id
    item.target_url = candidate.get("url", "")
    item.save(update_fields=["status", "target_external_id", "target_url", "updated_at"])
    if review.target_playlist_id and review.target_playlist:
        LibraryTrack.objects.create(
            playlist=review.target_playlist,
            title=item.source_track.title,
            artist=item.source_track.artist,
            album=item.source_track.album,
            duration_ms=item.source_track.duration_ms,
            external_id=candidate_id,
            external_url=candidate.get("url", ""),
            position=item.position,
        )
    review.matched += 1
    if not review.items.filter(status=LibraryTransferItem.Status.PENDING).exclude(pk=item.pk).exists():
        review.status = LibraryTransfer.Status.COMPLETED
        review.completed_at = timezone.now()
    review.save(update_fields=["matched", "status", "completed_at"])
    logger.info("Manual track match selected transfer_id=%s item_id=%s provider=%s", review.pk, item.pk, review.target_provider)
    messages.success(request, f"«{candidate.get('title') or item.source_track.title}» добавлен в целевой плейлист.")
    return redirect("transfer_review", transfer_id=review.pk)


@transaction.atomic
@require_POST
def skip_transfer_item(request, transfer_id, item_id):
    from django.utils import timezone

    review = get_object_or_404(
        LibraryTransfer.objects.select_for_update(),
        pk=transfer_id, profile=_profile(request),
    )
    item = get_object_or_404(
        LibraryTransferItem.objects.select_for_update(),
        pk=item_id, transfer=review, status=LibraryTransferItem.Status.PENDING,
    )
    if review.items.filter(
        status=LibraryTransferItem.Status.PENDING,
        position__lt=item.position,
    ).exists():
        messages.error(request, "Сначала разберись с предыдущими треками.")
        return redirect("transfer_review", transfer_id=review.pk)
    item.status = LibraryTransferItem.Status.SKIPPED
    item.save(update_fields=["status", "updated_at"])
    review.skipped += 1
    if not review.items.filter(status=LibraryTransferItem.Status.PENDING).exclude(pk=item.pk).exists():
        review.status = LibraryTransfer.Status.COMPLETED
        review.completed_at = timezone.now()
    review.save(update_fields=["skipped", "status", "completed_at"])
    logger.info("Manual track skipped transfer_id=%s item_id=%s", review.pk, item.pk)
    messages.info(request, f"«{item.source_track.title}» пропущен.")
    return redirect("transfer_review", transfer_id=review.pk)


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
    if Path(uploaded.name).suffix.lower() not in allowed_extensions or uploaded.size > 100 * 1024 * 1024:
        messages.error(request, "Поддерживаются аудиофайлы до 100 МБ в форматах MP3, WAV, FLAC, AIFF, OGG, AAC, AMR, WMA и MP2.")
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
        return redirect("library")
    messages.success(request, f"Трек «{track.title}» добавлен в библиотеку.")
    return redirect("library")
