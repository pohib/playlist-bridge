"""Authenticated local audio playback endpoint with HTTP byte-range support."""

import mimetypes
import re

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404

from .library_support import _profile
from .models import LibraryTrack

_RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK_SIZE = 64 * 1024


def _parse_byte_range(value, size):
    """Return an inclusive (start, end) range, or None for an invalid range."""
    match = _RANGE_PATTERN.fullmatch(value or "")
    if not match or size <= 0:
        return None

    first, last = match.groups()
    if not first and not last:
        return None
    if not first:
        suffix_length = int(last)
        if suffix_length <= 0:
            return None
        start = max(size - suffix_length, 0)
        end = size - 1
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        return None
    return start, end


def _stream_file(file_handle, length):
    remaining = length
    try:
        while remaining:
            chunk = file_handle.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        file_handle.close()


def _unsatisfied_range(size):
    response = HttpResponse(status=416)
    response["Content-Range"] = f"bytes */{size}"
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def stream_local_track(request, track_id):
    track = get_object_or_404(
        LibraryTrack.objects.select_related("playlist__profile"),
        pk=track_id,
        playlist__profile=_profile(request),
    )
    if not track.audio_file:
        raise Http404("У композиции нет локального аудиофайла.")

    try:
        size = track.audio_file.storage.size(track.audio_file.name)
    except (OSError, ValueError):
        raise Http404("Локальный аудиофайл недоступен.") from None

    content_type = mimetypes.guess_type(track.audio_file.name)[0] or "application/octet-stream"
    range_header = request.headers.get("Range")
    byte_range = _parse_byte_range(range_header, size) if range_header else None
    if range_header and byte_range is None:
        return _unsatisfied_range(size)

    start, end = byte_range if byte_range else (0, max(size - 1, 0))
    length = end - start + 1 if size else 0
    file_handle = track.audio_file.open("rb")
    file_handle.seek(start)

    if request.method == "HEAD":
        file_handle.close()
        response = HttpResponse(status=206 if byte_range else 200)
    else:
        response = StreamingHttpResponse(
            _stream_file(file_handle, length),
            status=206 if byte_range else 200,
            content_type=content_type,
        )

    response["Content-Length"] = str(length)
    response["Accept-Ranges"] = "bytes"
    if byte_range:
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
