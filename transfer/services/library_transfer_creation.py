"""Application workflow for creating cross-provider library transfers."""

import logging

from ..models import LibraryPlaylist
from .common import TransferError
from .library_transfer_matching import match_soundcloud_tracks, match_spotify_tracks
from .library_transfer_persistence import persist_library_transfer

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

    review = persist_library_transfer(
        playlist=playlist,
        target_provider=target_provider,
        tracks=tracks,
        matched=matched,
        unmatched=unmatched,
        target_id=target_id,
        target_url=target_url,
    )
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
