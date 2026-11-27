"""SoundCloud upload HTTP endpoint."""

from pathlib import Path

from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .library_support import _profile, _soundcloud_access
from .models import LibraryPlaylist, LibraryTrack
from .services.audio_file_validation import (
    SOUNDCLOUD_AUDIO_EXTENSIONS,
    has_audio_file_signature,
)
from .services.common import TransferError


@require_POST
def upload_track_to_soundcloud(request):
    uploaded = request.FILES.get("audio_file")
    title = (request.POST.get("title") or "").strip()
    artist = (request.POST.get("artist") or "").strip()
    description = (request.POST.get("description") or "").strip()
    if not uploaded or not title or not artist or len(title) > 100 or len(artist) > 100:
        messages.error(request, "Выбери аудиофайл и укажи название и исполнителя.")
        return redirect("library")
    extension = Path(uploaded.name).suffix.lower()
    if extension not in SOUNDCLOUD_AUDIO_EXTENSIONS or uploaded.size > 100 * 1024 * 1024:
        messages.error(request, "Поддерживаются аудиофайлы до 100 МБ в форматах MP3, WAV, FLAC, AIFF, OGG, AAC, AMR, WMA и MP2.")
        return redirect("library")
    if not has_audio_file_signature(uploaded, extension):
        messages.error(request, "Содержимое файла не соответствует заявленному аудиоформату.")
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
