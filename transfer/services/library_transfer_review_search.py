"""Provider search workflow for pending manual transfer-review items."""

from ..models import LibraryPlaylist, LibraryTransfer, LibraryTransferItem
from .common import TransferError
from .library_transfer_search import (
    normalize_soundcloud_search_results,
    normalize_spotify_search_results,
)


def search_pending_transfer_item(
    *,
    profile,
    transfer_id,
    item_id,
    query,
    spotify_access,
    soundcloud_access,
    safe_candidate_url,
):
    """Search the configured provider and persist candidates for the next pending item."""
    try:
        review = LibraryTransfer.objects.get(pk=transfer_id, profile=profile)
    except LibraryTransfer.DoesNotExist as exc:
        raise TransferError("Перенос не найден.") from exc

    try:
        item = LibraryTransferItem.objects.select_related("source_track").get(
            pk=item_id,
            transfer=review,
            status=LibraryTransferItem.Status.PENDING,
        )
    except LibraryTransferItem.DoesNotExist as exc:
        raise TransferError("Композиция уже обработана или не найдена.") from exc

    if review.items.filter(
        status=LibraryTransferItem.Status.PENDING,
        position__lt=item.position,
    ).exists():
        raise TransferError(
            "Сначала разберись с предыдущими треками, чтобы сохранить порядок."
        )
    if not query or len(query) > 180:
        raise TransferError("Введи поисковый запрос длиной до 180 символов.")

    if review.target_provider == LibraryPlaylist.Provider.SPOTIFY:
        client, token = spotify_access()
        results = client.search_tracks(token, query)
        candidates = normalize_spotify_search_results(results, safe_candidate_url)
    elif review.target_provider == LibraryPlaylist.Provider.SOUNDCLOUD:
        client, token = soundcloud_access()
        results = client.search_tracks(token, query)
        candidates = normalize_soundcloud_search_results(results, safe_candidate_url)
    else:
        raise TransferError("Неизвестный целевой музыкальный сервис.")

    item.candidates = candidates
    item.save(update_fields=["candidates", "updated_at"])
    return review, item, candidates
