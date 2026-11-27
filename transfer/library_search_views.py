"""Library source opening and cross-provider search endpoints."""

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from .library_support import _profile
from .services.provider_catalog_access import get_catalog_access
from .models import LibraryPlaylist, LibraryTrack
from .services import library_source_search_service
from .services.library_source_links import safe_provider_source_url


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
        title, artist, providers = library_source_search_service.parse_library_source_search_request(payload)
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Некорректный запрос поиска."},
            status=400,
        )

    result = library_source_search_service.search_library_sources(
        title,
        artist,
        providers,
        spotify_access=lambda: get_catalog_access("spotify"),
        soundcloud_access=lambda: get_catalog_access("soundcloud"),
    )
    return JsonResponse(result)
