"""Transactional persistence for completed library-transfer matching runs."""

from django.db import transaction
from django.utils import timezone

from ..models import LibraryPlaylist, LibraryTrack, LibraryTransfer, LibraryTransferItem


@transaction.atomic
def persist_library_transfer(
    *,
    playlist,
    target_provider,
    tracks,
    matched,
    unmatched,
    target_id,
    target_url,
):
    """Persist the local target playlist, matched tracks and review items atomically."""
    target_playlist = LibraryPlaylist.objects.create(
        profile=playlist.profile,
        title=f"{playlist.title} · {target_provider.title()}"[:120],
        provider=target_provider,
        external_url=target_url,
        description=f"Перенос из библиотеки · найдено {len(matched)} из {len(tracks)}",
    )
    LibraryTrack.objects.bulk_create([
        LibraryTrack(
            playlist=target_playlist,
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_ms=track.duration_ms,
            external_id=matched[track.pk]["id"],
            external_url=matched[track.pk]["url"],
            position=index,
        )
        for index, track in enumerate(tracks)
        if track.pk in matched
    ])

    pending_by_id = {track.pk: candidates for track, candidates in unmatched}
    review = LibraryTransfer.objects.create(
        profile=playlist.profile,
        source_playlist=playlist,
        target_provider=target_provider,
        target_playlist=target_playlist,
        provider_playlist_id=str(target_id),
        target_url=target_url,
        status=(
            LibraryTransfer.Status.REVIEW
            if unmatched else LibraryTransfer.Status.COMPLETED
        ),
        total=len(tracks),
        matched=len(matched),
        completed_at=timezone.now() if not unmatched else None,
    )
    LibraryTransferItem.objects.bulk_create([
        LibraryTransferItem(
            transfer=review,
            source_track=track,
            position=index,
            status=(
                LibraryTransferItem.Status.MATCHED
                if track.pk in matched
                else LibraryTransferItem.Status.PENDING
            ),
            candidates=pending_by_id.get(track.pk, []),
            target_external_id=matched.get(track.pk, {}).get("id", ""),
            target_url=matched.get(track.pk, {}).get("url", ""),
        )
        for index, track in enumerate(tracks)
    ])
    return review
