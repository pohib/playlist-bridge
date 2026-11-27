"""VK playlist/track import and artwork refresh endpoints."""

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .library_support import _profile
from .models import LibraryPlaylist
from .services.common import TransferError, parse_vk_playlist_url, parse_vk_track_url
from .services import library_import_vk, vk_client

logger = logging.getLogger(__name__)

VKClient = vk_client.VKClient
refresh_vk_track_metadata = library_import_vk.refresh_vk_track_metadata
save_vk_playlist = library_import_vk.save_vk_playlist
save_vk_track = library_import_vk.save_vk_track

@require_POST
def import_vk_playlist(request):
    source_url = (request.POST.get("source_url") or "").strip()
    try:
        owner_id, playlist_id, access_key = parse_vk_playlist_url(source_url)
        logger.info("VK public playlist import started owner_id=%s playlist_id=%s has_access_key=%s", owner_id, playlist_id, bool(access_key))
        api = VKClient(version=settings.VK_API_VERSION)
        profile = _profile(request)
        playlist, track_count = library_import_vk.import_vk_playlist(
            profile,
            api,
            source_url,
        )
    except (ValueError, TransferError) as exc:
        logger.warning("VK public playlist import rejected: %s", str(exc)[:240])
        messages.error(request, str(exc) if isinstance(exc, TransferError) else "Укажи корректную ссылку на публичный плейлист VK.")
        return redirect("library")
    except Exception:
        logger.exception("Unexpected error during VK public playlist import")
        messages.error(request, "Не удалось импортировать плейлист VK. Подробности записаны в журнал.")
        return redirect("library")
    logger.info("VK public playlist import completed playlist_id=%s track_count=%s", playlist.pk, track_count)
    messages.success(request, f"Импортировано «{playlist.title}»: {track_count} композиций.")
    return redirect("library")

@require_POST
def import_vk_track(request):
    source_url = (request.POST.get("source_url") or "").strip()
    try:
        parse_vk_track_url(source_url)
        profile = _profile(request)
        playlist_id = (request.POST.get("playlist_id") or "").strip()
        playlist = (
            get_object_or_404(LibraryPlaylist, pk=playlist_id, profile=profile)
            if playlist_id else None
        )
        playlist, track = library_import_vk.import_vk_track(
            profile,
            VKClient(version=settings.VK_API_VERSION),
            source_url,
            playlist=playlist,
        )
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    except Http404:
        raise
    except Exception:
        logger.exception("Unexpected error during VK track import")
        messages.error(request, "Не удалось импортировать трек VK.")
        return redirect("library")
    messages.success(request, f"Трек «{track.title}» добавлен в «{playlist.title}».")
    return redirect("playlist_detail", playlist_id=playlist.pk)




@login_required
@require_POST
def refresh_vk_artwork(request, playlist_id):
    playlist = get_object_or_404(LibraryPlaylist, pk=playlist_id, profile=_profile(request))
    if playlist.provider != LibraryPlaylist.Provider.VK:
        messages.error(request, "Обновление обложек доступно только для плейлистов VK.")
        return redirect("playlist_detail", playlist_id=playlist.pk)
    try:
        updated = library_import_vk.refresh_vk_playlist_artwork(
            playlist,
            VKClient(version=settings.VK_API_VERSION),
        )
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("playlist_detail", playlist_id=playlist.pk)
    messages.success(request, f"Обновлены данные {updated} композиций. Обложки появятся там, где VK их предоставляет.")
    return redirect("playlist_detail", playlist_id=playlist.pk)
