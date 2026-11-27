"""Review and finalize track matches for cross-provider library transfers."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .library_support import (
    _profile,
    _safe_candidate_url,
    _soundcloud_access,
    _spotify_access,
)
from .models import LibraryPlaylist, LibraryTransfer, LibraryTransferItem
from .services import TransferError, library_transfer_review
from .services.library_transfer_search import (
    normalize_soundcloud_search_results,
    normalize_spotify_search_results,
)


@require_GET
def open_transfer_target(request, transfer_id):
    review = get_object_or_404(LibraryTransfer, pk=transfer_id, profile=_profile(request))
    target_url = _safe_candidate_url(review.target_url, review.target_provider)
    if not target_url:
        messages.error(request, "Ссылка на целевой плейлист недоступна.")
        return redirect("transfer_review", transfer_id=review.pk)
    return redirect(target_url)


@require_GET
def open_transfer_candidate(request, transfer_id, item_id, candidate_id):
    review = get_object_or_404(LibraryTransfer, pk=transfer_id, profile=_profile(request))
    item = get_object_or_404(LibraryTransferItem, pk=item_id, transfer=review)
    candidate = next(
        (entry for entry in item.candidates if entry.get("id") == candidate_id),
        None,
    )
    candidate_url = _safe_candidate_url(
        candidate.get("url") if candidate else "",
        review.target_provider,
    )
    if not candidate_url:
        messages.error(request, "Ссылка на вариант недоступна.")
        return redirect("transfer_review", transfer_id=review.pk)
    return redirect(candidate_url)


@require_GET
def transfer_review(request, transfer_id):
    review = get_object_or_404(
        LibraryTransfer.objects.prefetch_related("items__source_track"),
        pk=transfer_id,
        profile=_profile(request),
    )
    pending = list(
        review.items.filter(status=LibraryTransferItem.Status.PENDING).order_by("position")
    )
    first_pending_id = pending[0].pk if pending else None
    return render(request, "transfer/transfer_review.html", {
        "transfer": review,
        "items": review.items.select_related("source_track").all(),
        "first_pending_id": first_pending_id,
    })


@require_POST
def search_transfer_item(request, transfer_id, item_id):
    review = get_object_or_404(LibraryTransfer, pk=transfer_id, profile=_profile(request))
    item = get_object_or_404(
        LibraryTransferItem.objects.select_related("source_track"),
        pk=item_id,
        transfer=review,
        status=LibraryTransferItem.Status.PENDING,
    )
    if review.items.filter(
        status=LibraryTransferItem.Status.PENDING,
        position__lt=item.position,
    ).exists():
        messages.error(
            request,
            "Сначала разберись с предыдущими треками, чтобы сохранить порядок.",
        )
        return redirect("transfer_review", transfer_id=review.pk)

    query = (request.POST.get("query") or "").strip()
    if not query or len(query) > 180:
        messages.error(request, "Введи поисковый запрос длиной до 180 символов.")
        return redirect("transfer_review", transfer_id=review.pk)

    try:
        if review.target_provider == LibraryPlaylist.Provider.SPOTIFY:
            client, token = _spotify_access(request)
            results = client.search_tracks(token, query)
            candidates = normalize_spotify_search_results(
                results,
                _safe_candidate_url,
            )
        else:
            client, token = _soundcloud_access(request)
            results = client.search_tracks(token, query)
            candidates = normalize_soundcloud_search_results(
                results,
                _safe_candidate_url,
            )
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("transfer_review", transfer_id=review.pk)

    item.candidates = candidates
    item.save(update_fields=["candidates", "updated_at"])
    messages.success(
        request,
        f"Найдено вариантов: {len(item.candidates)}. Выбери правильную композицию.",
    )
    return redirect("transfer_review", transfer_id=review.pk)


@require_POST
def select_transfer_candidate(request, transfer_id, item_id):
    try:
        review, item, candidate = library_transfer_review.select_transfer_candidate(
            profile=_profile(request),
            transfer_id=transfer_id,
            item_id=item_id,
            candidate_id=(request.POST.get("candidate_id") or "").strip(),
            spotify_access=lambda: _spotify_access(request),
            soundcloud_access=lambda: _soundcloud_access(request),
            safe_candidate_url=_safe_candidate_url,
        )
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("transfer_review", transfer_id=transfer_id)

    messages.success(
        request,
        f"«{candidate.get('title') or item.source_track.title}» добавлен в целевой плейлист.",
    )
    return redirect("transfer_review", transfer_id=review.pk)


@require_POST
def skip_transfer_item(request, transfer_id, item_id):
    try:
        review, item = library_transfer_review.skip_transfer_item(
            profile=_profile(request),
            transfer_id=transfer_id,
            item_id=item_id,
        )
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("transfer_review", transfer_id=transfer_id)

    messages.info(request, f"«{item.source_track.title}» пропущен.")
    return redirect("transfer_review", transfer_id=review.pk)
