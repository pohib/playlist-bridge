"""Authenticated provider artwork proxy with strict upstream URL validation."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from .library_support import _profile
from .models import LibraryTrack
from .services.library_artwork_proxy import ArtworkProxyError, fetch_provider_artwork


@login_required
@require_GET
def library_cover_proxy(request):
    """Serve approved provider artwork from our origin to honor the strict image CSP."""
    track_id = request.GET.get("track_id", "")
    if not track_id or len(track_id) > 36:
        return HttpResponseBadRequest("Invalid artwork reference.")
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    try:
        body, content_type = fetch_provider_artwork(track.cover_url)
    except ArtworkProxyError as exc:
        response_class = (
            HttpResponseBadRequest if exc.status_code == 400
            else HttpResponseNotFound
        )
        message = (
            "Invalid artwork reference."
            if exc.status_code == 400
            else "Artwork is currently unavailable."
        )
        return response_class(message)

    response = HttpResponse(body, content_type=content_type)
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response
