"""SoundCloud upload HTTP endpoint."""

from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .library_support import _profile, _soundcloud_access
from .services.common import TransferError
from .services.library_soundcloud_upload import upload_soundcloud_track


@require_POST
def upload_track_to_soundcloud(request):
    uploaded = request.FILES.get("audio_file")
    title = (request.POST.get("title") or "").strip()
    artist = (request.POST.get("artist") or "").strip()
    description = (request.POST.get("description") or "").strip()
    try:
        upload_soundcloud_track(
            profile_provider=lambda: _profile(request),
            uploaded=uploaded,
            title=title,
            artist=artist,
            description=description,
            soundcloud_access=lambda: _soundcloud_access(request),
        )
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("library")

    messages.success(
        request,
        f"Трек «{title}» загружен в SoundCloud и добавлен в библиотеку.",
    )
    return redirect("library")
