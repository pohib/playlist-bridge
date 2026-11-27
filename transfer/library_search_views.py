"""Library source opening and cross-provider search endpoints."""

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from .library_support import (
    _profile,
    _soundcloud_access,
    _spotify_access,
)
from .models import LibraryPlaylist, LibraryTrack
from .services.library_source_links import safe_provider_source_url
from .services.library_source_search_service import (
    LibrarySourceSearchError,
    parse_library_source_search_request,
    search_library_sources as search_library_sources_service,
)


@require_GET
def open_playlist_source(request, playlist_id):
    playlist = get_object_or_404(
        LibraryPlaylist, pk=playlist_id, profile=_profile(request)
    )
    source_url = safe_provider_source_url(playlist.external_url, playlist.provider)
    if not source_url:
        return redirect("library")
    return HttpResponseRedirect(source_url)


@require_GET
def open_track_source(request, track_id):
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist__profile"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    source_url = safe_provider_source_url(
        track.external_url,
        track.playlist.provider,
    )
    if not source_url:
        return redirect("library")
    return HttpResponseRedirect(source_url)


@login_required
@require_POST
def search_library_sources(request):
    """Validate the HTTP payload and delegate provider search orchestration."""
    try:
        payload = json.loads(request.body or b"{}")
        title, artist, providers = parse_library_source_search_request(payload)
    except (TypeError, ValueError) as exc:
        message = (
            str(exc)
            if isinstance(exc, LibrarySourceSearchError)
            else "Некорректный JSON запроса."
        )
        return JsonResponse({"error": message}, status=400)

    result = search_library_sources_service(
        title,
        artist,
        providers,
        spotify_access=lambda: _spotify_access(request),
        soundcloud_access=lambda: _soundcloud_access(request),
    )
    return JsonResponse(result)
