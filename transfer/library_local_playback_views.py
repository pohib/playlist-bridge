"""Authenticated local audio playback endpoint."""

import mimetypes

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from .library_support import _profile
from .models import LibraryTrack


@login_required
def stream_local_track(request, track_id):
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist__profile"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    if not track.audio_file:
        raise Http404("У композиции нет локального аудиофайла.")
    content_type = mimetypes.guess_type(track.audio_file.name)[0] or "application/octet-stream"
    response = FileResponse(
        track.audio_file.open("rb"),
        content_type=content_type,
        as_attachment=False,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
