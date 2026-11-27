"""VK playlist/track import and artwork refresh endpoints."""

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .library_support import _profile
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
