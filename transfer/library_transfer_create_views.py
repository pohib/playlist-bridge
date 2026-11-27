"""Create a cross-provider transfer from a local library playlist."""

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .library_support import _profile, _safe_candidate_url
from .models import LibraryPlaylist
from .services import SoundCloudClient, SpotifyClient, TransferError
from .services.credential_service import get_access_token, get_session_fingerprint
from .services.library_transfer_creation import create_library_transfer


@require_POST
def transfer_library_playlist(request, playlist_id):
    playlist = get_object_or_404(
        LibraryPlaylist.objects.prefetch_related("tracks"),
        pk=playlist_id,
        profile=_profile(request),
    )
    target = request.POST.get("target_provider", "").strip()
    if target not in {"spotify", "soundcloud"}:
        messages.error(request, "Выбери поддерживаемый целевой сервис.")
        return redirect("playlist_detail", playlist_id=playlist.pk)
    tracks = list(playlist.tracks.all())
    if not tracks:
        messages.error(request, "В плейлисте нет композиций для переноса.")
        return redirect("playlist_detail", playlist_id=playlist.pk)
    if len(tracks) > 100:
        messages.error(request, "Пока можно переносить не более 100 композиций за один запуск.")
        return redirect("playlist_detail", playlist_id=playlist.pk)

    fingerprint = get_session_fingerprint(request)
    try:
        if target == LibraryPlaylist.Provider.SPOTIFY:
            client = SpotifyClient(
                settings.SPOTIFY_CLIENT_ID,
                settings.SPOTIFY_CLIENT_SECRET,
                settings.SPOTIFY_REDIRECT_URI,
            )
        else:
            client = SoundCloudClient(
                settings.SOUNDCLOUD_CLIENT_ID,
                settings.SOUNDCLOUD_CLIENT_SECRET,
                settings.SOUNDCLOUD_REDIRECT_URI,
            )
        token, _ = get_access_token(fingerprint, target, client)
        review, matched, unmatched = create_library_transfer(
            playlist=playlist,
            target_provider=target,
            tracks=tracks,
            client=client,
            token=token,
            safe_candidate_url=_safe_candidate_url,
        )
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("playlist_detail", playlist_id=playlist.pk)

    messages.success(
        request,
        f"Создан плейлист {target.title()}: найдено {len(matched)} из {len(tracks)}. "
        f"Требуют ручного сопоставления: {len(unmatched)}.",
    )
    return redirect("transfer_review", transfer_id=review.pk)
