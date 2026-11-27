"""Read operations for the manual library-transfer review workflow."""

from django.shortcuts import get_object_or_404

from ..models import LibraryTransfer, LibraryTransferItem


def get_transfer_review_page(*, profile, transfer_id):
    """Return the owned transfer and ordered review-page context."""
    review = get_object_or_404(
        LibraryTransfer.objects.prefetch_related("items__source_track"),
        pk=transfer_id,
        profile=profile,
    )
    first_pending_id = (
        review.items.filter(status=LibraryTransferItem.Status.PENDING)
        .order_by("position")
        .values_list("pk", flat=True)
        .first()
    )
    items = review.items.select_related("source_track").all()
    return review, items, first_pending_id


def get_transfer_target_url(*, profile, transfer_id, safe_candidate_url):
    """Return an owned transfer and its validated target playlist URL."""
    review = get_object_or_404(
        LibraryTransfer,
        pk=transfer_id,
        profile=profile,
    )
    return review, safe_candidate_url(review.target_url, review.target_provider)


def get_transfer_candidate_url(
    *,
    profile,
    transfer_id,
    item_id,
    candidate_id,
    safe_candidate_url,
):
    """Return an owned transfer and a validated URL for one stored candidate."""
    review = get_object_or_404(
        LibraryTransfer,
        pk=transfer_id,
        profile=profile,
    )
    item = get_object_or_404(
        LibraryTransferItem,
        pk=item_id,
        transfer=review,
    )
    candidate = next(
        (entry for entry in item.candidates if entry.get("id") == candidate_id),
        None,
    )
    candidate_url = safe_candidate_url(
        candidate.get("url") if candidate else "",
        review.target_provider,
    )
    return review, candidate_url
