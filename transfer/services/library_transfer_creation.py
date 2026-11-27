"""Application workflow for creating cross-provider library transfers."""

import logging

from django.db import transaction
from django.utils import timezone

from ..models import LibraryPlaylist, LibraryTrack, LibraryTransfer, LibraryTransferItem
from .common import TransferError
from .library_transfer_matching import match_soundcloud_tracks, match_spotify_tracks

logger = logging.getLogger(__name__)


def create_library_transfer(
    *,
    playlist,
    target_provider,
    tracks,
    client,
    token,
    safe_candidate_url,
):
    """Match source tracks, create the provider playlist and persist review state.

    Provider calls happen before local persistence because a database transaction
    cannot roll back remote API side effects. The local mirror and review records
    are then written together in one transaction.
    """
    tracks = list(tracks)
    if target_provider == LibraryPlaylist.Provider.SPOTIFY:
        matched, unmatched = match_spotify_tracks(
            tracks,
            client=client,
            token=token,
            safe_candidate_url=safe_candidate_url,
        )
        target_ids = [
            matched[track.pk]["uri"]
            for track in tracks
            if track.pk in matched and matched[track.pk].get("uri")
        ]
        target_id = client.create_playlist(token, playlist.title) if target_ids else ""
        if target_id:
            client.add_items(token, target_id, target_ids)
        target_url = (
            f"https://open.spotify.com/playlist/{target_id}" if target_id else ""
        )
    elif target_provider == LibraryPlaylist.Provider.SOUNDCLOUD:
        matched, unmatched = match_soundcloud_tracks(
            tracks,
            client=client,
            token=token,
            safe_candidate_url=safe_candidate_url,
        )
        target_ids = [
            matched[track.pk]["id"]
            for track in tracks
            if track.pk in matched and matched[track.pk].get("id")
        ]
        if target_ids:
            result = client.create_playlist(token, playlist.title, target_ids)
            target_id = str(result["id"])
            target_url = (
                safe_candidate_url(result.get("permalink_url"), "soundcloud")
                or "https://soundcloud.com"
            )
        else:
            target_id = ""
            target_url = ""
    else:
        raise TransferError("Неизвестный целевой музыкальный сервис.")

    with transaction.atomic():
        target_playlist = LibraryPlaylist.objects.create(
            profile=playlist.profile,
            title=f"{playlist.title} · {target_provider.title()}"[:120],
            provider=target_provider,
            external_url=target_url,
            description=(
                f"Перенос из библиотеки · найдено {len(matched)} из {len(tracks)}"
            ),
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

    logger.info(
        "Library transfer created transfer_id=%s profile_id=%s target=%s total=%s matched=%s pending=%s",
        review.pk,
        playlist.profile_id,
        target_provider,
        len(tracks),
        len(matched),
        len(unmatched),
    )
    return review, matched, unmatched
