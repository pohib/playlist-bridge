"""Create a cross-provider transfer from a local library playlist."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .library_support import _profile, _safe_candidate_url
from .models import LibraryPlaylist
from .services.common import TransferError
from .services.credential_service import get_session_fingerprint
from .services.library_transfer_workflow import create_library_transfer_workflow


@require_POST
def transfer_library_playlist(request, playlist_id):
    playlist = get_object_or_404(
        LibraryPlaylist.objects.prefetch_related("tracks"),
        pk=playlist_id,
        profile=_profile(request),
    )
    target = request.POST.get("target_provider", "").strip()
    fingerprint = get_session_fingerprint(request)
    try:
        review, matched, unmatched = create_library_transfer_workflow(
            playlist=playlist,
            target_provider=target,
            fingerprint=fingerprint,
            safe_candidate_url=_safe_candidate_url,
        )
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("playlist_detail", playlist_id=playlist.pk)

    messages.success(
        request,
        f"Создан плейлист {target.title()}: найдено {len(matched)} из {review.total}. "
        f"Требуют ручного сопоставления: {len(unmatched)}.",
    )
    return redirect("transfer_review", transfer_id=review.pk)
