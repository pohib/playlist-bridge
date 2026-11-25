import logging
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .library_support import _profile, _soundcloud_access, _spotify_access
from .models import LibraryPlaylist, LibraryTrack
from .services import TransferError, VKClient, parse_vk_playlist_url, parse_vk_track_url

logger = logging.getLogger(__name__)


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
