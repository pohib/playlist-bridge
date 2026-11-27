"""Application services for the manual library-transfer review workflow."""

import logging

from django.db import transaction
from django.utils import timezone

from ..models import LibraryTrack, LibraryTransfer, LibraryTransferItem
from .common import TransferError
from .library_transfer_review_provider import apply_review_candidate_to_provider

logger = logging.getLogger(__name__)


def _locked_review_and_item(*, profile, transfer_id, item_id):
    try:
        review = LibraryTransfer.objects.select_for_update().get(
            pk=transfer_id,
            profile=profile,
        )
    except LibraryTransfer.DoesNotExist as exc:
        raise TransferError("Перенос не найден.") from exc

    try:
        item = LibraryTransferItem.objects.select_for_update().select_related(
            "source_track",
        ).get(
            pk=item_id,
            transfer=review,
            status=LibraryTransferItem.Status.PENDING,
        )
    except LibraryTransferItem.DoesNotExist as exc:
        raise TransferError("Композиция уже обработана или не найдена.") from exc

    return review, item


def _ensure_item_is_next(review, item):
    if review.items.filter(
        status=LibraryTransferItem.Status.PENDING,
        position__lt=item.position,
    ).exists():
        raise TransferError("Сначала разберись с предыдущими треками.")


@transaction.atomic
def select_transfer_candidate(
    *,
    profile,
    transfer_id,
    item_id,
    candidate_id,
    spotify_access,
    soundcloud_access,
    safe_candidate_url,
):
    """Apply a selected provider match and persist the review state atomically."""
    review, item = _locked_review_and_item(
        profile=profile,
        transfer_id=transfer_id,
        item_id=item_id,
    )
    _ensure_item_is_next(review, item)

    candidate = next(
        (entry for entry in item.candidates if entry.get("id") == candidate_id),
        None,
    )
    if not candidate:
        raise TransferError(
            "Выбранный вариант отсутствует в результатах поиска. Выполни поиск повторно."
        )

    playlist_id, target_url = apply_review_candidate_to_provider(
        review=review,
        item=item,
        candidate=candidate,
        candidate_id=candidate_id,
        spotify_access=spotify_access,
        soundcloud_access=soundcloud_access,
        safe_candidate_url=safe_candidate_url,
    )
    review.provider_playlist_id = playlist_id
    review.target_url = target_url

    if review.target_playlist:
        review.target_playlist.external_url = review.target_url
        review.target_playlist.save(update_fields=["external_url", "updated_at"])
    review.save(update_fields=["provider_playlist_id", "target_url"])

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
    if not review.items.filter(
        status=LibraryTransferItem.Status.PENDING,
    ).exclude(pk=item.pk).exists():
        review.status = LibraryTransfer.Status.COMPLETED
        review.completed_at = timezone.now()
    review.save(update_fields=["matched", "status", "completed_at"])

    logger.info(
        "Manual track match selected transfer_id=%s item_id=%s",
        review.pk,
        item.pk,
    )
    return review, item, candidate


@transaction.atomic
def skip_transfer_item(*, profile, transfer_id, item_id):
    """Skip the next pending item and complete the review when nothing remains."""
    review, item = _locked_review_and_item(
        profile=profile,
        transfer_id=transfer_id,
        item_id=item_id,
    )
    _ensure_item_is_next(review, item)

    item.status = LibraryTransferItem.Status.SKIPPED
    item.save(update_fields=["status", "updated_at"])
    review.skipped += 1
    if not review.items.filter(
        status=LibraryTransferItem.Status.PENDING,
    ).exclude(pk=item.pk).exists():
        review.status = LibraryTransfer.Status.COMPLETED
        review.completed_at = timezone.now()
    review.save(update_fields=["skipped", "status", "completed_at"])

    logger.info("Manual track skipped transfer_id=%s item_id=%s", review.pk, item.pk)
    return review, item
