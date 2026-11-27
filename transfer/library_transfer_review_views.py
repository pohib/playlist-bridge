"""Review and finalize track matches for cross-provider library transfers."""

import logging

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .library_support import _profile, _safe_candidate_url, _soundcloud_access, _spotify_access
from .models import LibraryTrack, LibraryTransfer, LibraryTransferItem
from .services import TransferError

logger = logging.getLogger(__name__)

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
    pending = list(review.items.filter(status=LibraryTransferItem.Status.PENDING).order_by("position"))
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
        pk=item_id, transfer=review, status=LibraryTransferItem.Status.PENDING,
    )
    if review.items.filter(
        status=LibraryTransferItem.Status.PENDING,
        position__lt=item.position,
    ).exists():
        messages.error(request, "Сначала разберись с предыдущими треками, чтобы сохранить порядок.")
        return redirect("transfer_review", transfer_id=review.pk)
    query = (request.POST.get("query") or "").strip()
    if not query or len(query) > 180:
        messages.error(request, "Введи поисковый запрос длиной до 180 символов.")
        return redirect("transfer_review", transfer_id=review.pk)
    try:
        if review.target_provider == "spotify":
            client, token = _spotify_access(request)
            results = client.search_tracks(token, query)
            candidates = [{
                "id": str(result.get("id") or ""),
                "uri": str(result.get("uri") or ""),
                "title": str(result.get("name") or "")[:180],
                "artist": ", ".join(str(artist.get("name") or "") for artist in result.get("artists", []))[:180],
                "duration_ms": int(result.get("duration_ms") or 0),
                "url": _safe_candidate_url((result.get("external_urls") or {}).get("spotify", ""), "spotify"),
            } for result in results if result.get("id") and result.get("uri")]
        else:
            client, token = _soundcloud_access(request)
            results = client.search_tracks(token, query)
            candidates = [{
                "id": str(result.get("id") or ""),
                "uri": str(result.get("urn") or result.get("id") or ""),
                "title": str(result.get("title") or "")[:180],
                "artist": str(result.get("metadata_artist") or (result.get("user") or {}).get("username") or "")[:180],
                "duration_ms": int(result.get("duration") or 0),
                "url": _safe_candidate_url(result.get("permalink_url"), "soundcloud"),
            } for result in results if result.get("id")]
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("transfer_review", transfer_id=review.pk)
    item.candidates = candidates[:10]
    item.save(update_fields=["candidates", "updated_at"])
    messages.success(request, f"Найдено вариантов: {len(item.candidates)}. Выбери правильную композицию.")
    return redirect("transfer_review", transfer_id=review.pk)


@transaction.atomic
@require_POST
def select_transfer_candidate(request, transfer_id, item_id):
    from django.utils import timezone

    review = get_object_or_404(
        LibraryTransfer.objects.select_for_update(),
        pk=transfer_id, profile=_profile(request),
    )
    item = get_object_or_404(
        LibraryTransferItem.objects.select_for_update().select_related("source_track"),
        pk=item_id, transfer=review, status=LibraryTransferItem.Status.PENDING,
    )
    if review.items.filter(
        status=LibraryTransferItem.Status.PENDING,
        position__lt=item.position,
    ).exists():
        messages.error(request, "Сначала сопоставь или пропусти предыдущие треки.")
        return redirect("transfer_review", transfer_id=review.pk)
    candidate_id = (request.POST.get("candidate_id") or "").strip()
    candidate = next((entry for entry in item.candidates if entry.get("id") == candidate_id), None)
    if not candidate:
        messages.error(request, "Выбранный вариант отсутствует в результатах поиска. Выполни поиск повторно.")
        return redirect("transfer_review", transfer_id=review.pk)
    try:
        if review.target_provider == "spotify":
            client, token = _spotify_access(request)
            if not candidate.get("uri"):
                raise TransferError("Spotify не вернул URI выбранной композиции.")
            if not review.provider_playlist_id:
                review.provider_playlist_id = client.create_playlist(token, review.source_playlist.title)
                review.target_url = f"https://open.spotify.com/playlist/{review.provider_playlist_id}"
                client.add_items(token, review.provider_playlist_id, [candidate["uri"]])
            else:
                insert_position = review.items.filter(
                    status=LibraryTransferItem.Status.MATCHED,
                    position__lt=item.position,
                ).count()
                client.add_items(token, review.provider_playlist_id, [candidate["uri"]], position=insert_position)
        else:
            client, token = _soundcloud_access(request)
            existing = list(
                review.items.filter(status=LibraryTransferItem.Status.MATCHED)
                .exclude(target_external_id="")
                .order_by("position")
                .values_list("position", "target_external_id")
            )
            ordered = sorted(existing + [(item.position, candidate_id)], key=lambda value: value[0])
            ordered_ids = [track_id for _, track_id in ordered]
            if not review.provider_playlist_id:
                result = client.create_playlist(token, review.source_playlist.title, ordered_ids)
                review.provider_playlist_id = str(result["id"])
                review.target_url = _safe_candidate_url(result.get("permalink_url"), "soundcloud") or "https://soundcloud.com"
            else:
                client.update_playlist_tracks(token, review.provider_playlist_id, ordered_ids)
        if review.target_playlist:
            review.target_playlist.external_url = review.target_url
            review.target_playlist.save(update_fields=["external_url", "updated_at"])
        review.save(update_fields=["provider_playlist_id", "target_url"])
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("transfer_review", transfer_id=review.pk)

    item.status = LibraryTransferItem.Status.MATCHED
    item.target_external_id = candidate_id
    item.target_url = candidate.get("url", "")
    item.save(update_fields=["status", "target_external_id", "target_url", "updated_at"])
    if review.provider_playlist_id and review.target_playlist:
        LibraryTrack.objects.create(
            playlist=review.target_playlist,
            title=item.source_track.title,
            artist=item.source_track.artist,
            album=item.source_track.album,
            duration_ms=item.source_track.duration_ms,
            external_id=candidate_id,
            external_url=candidate.get("url", ""),
            position=item.position,
        )
    review.matched += 1
    if not review.items.filter(status=LibraryTransferItem.Status.PENDING).exclude(pk=item.pk).exists():
        review.status = LibraryTransfer.Status.COMPLETED
        review.completed_at = timezone.now()
    review.save(update_fields=["matched", "status", "completed_at"])
    logger.info("Manual track match selected transfer_id=%s item_id=%s provider=%s", review.pk, item.pk, review.target_provider)
    messages.success(request, f"«{candidate.get('title') or item.source_track.title}» добавлен в целевой плейлист.")
    return redirect("transfer_review", transfer_id=review.pk)


@transaction.atomic
@require_POST
def skip_transfer_item(request, transfer_id, item_id):
    from django.utils import timezone

    review = get_object_or_404(
        LibraryTransfer.objects.select_for_update(),
        pk=transfer_id, profile=_profile(request),
    )
    item = get_object_or_404(
        LibraryTransferItem.objects.select_for_update(),
        pk=item_id, transfer=review, status=LibraryTransferItem.Status.PENDING,
    )
    if review.items.filter(
        status=LibraryTransferItem.Status.PENDING,
        position__lt=item.position,
    ).exists():
        messages.error(request, "Сначала разберись с предыдущими треками.")
        return redirect("transfer_review", transfer_id=review.pk)
    item.status = LibraryTransferItem.Status.SKIPPED
    item.save(update_fields=["status", "updated_at"])
    review.skipped += 1
    if not review.items.filter(status=LibraryTransferItem.Status.PENDING).exclude(pk=item.pk).exists():
        review.status = LibraryTransfer.Status.COMPLETED
        review.completed_at = timezone.now()
    review.save(update_fields=["skipped", "status", "completed_at"])
    logger.info("Manual track skipped transfer_id=%s item_id=%s", review.pk, item.pk)
    messages.info(request, f"«{item.source_track.title}» пропущен.")
    return redirect("transfer_review", transfer_id=review.pk)
