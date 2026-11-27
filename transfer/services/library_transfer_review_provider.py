"""Provider API operations for manual transfer-review candidate selection."""

from ..models import LibraryPlaylist, LibraryTransferItem
from .common import TransferError


def apply_review_candidate_to_provider(
    *,
    review,
    item,
    candidate,
    candidate_id,
    spotify_access,
    soundcloud_access,
    safe_candidate_url,
):
    """Apply one validated candidate remotely and return target playlist metadata."""
    if review.target_provider == LibraryPlaylist.Provider.SPOTIFY:
        client, token = spotify_access()
        if not candidate.get("uri"):
            raise TransferError("Spotify не вернул URI выбранной композиции.")

        playlist_id = review.provider_playlist_id
        target_url = review.target_url
        if not playlist_id:
            playlist_id = client.create_playlist(token, review.source_playlist.title)
            target_url = f"https://open.spotify.com/playlist/{playlist_id}"
            client.add_items(token, playlist_id, [candidate["uri"]])
        else:
            insert_position = review.items.filter(
                status=LibraryTransferItem.Status.MATCHED,
                position__lt=item.position,
            ).count()
            client.add_items(
                token,
                playlist_id,
                [candidate["uri"]],
                position=insert_position,
            )
        return playlist_id, target_url

    if review.target_provider == LibraryPlaylist.Provider.SOUNDCLOUD:
        client, token = soundcloud_access()
        existing = list(
            review.items.filter(status=LibraryTransferItem.Status.MATCHED)
            .exclude(target_external_id="")
            .order_by("position")
            .values_list("position", "target_external_id")
        )
        ordered = sorted(
            existing + [(item.position, candidate_id)],
            key=lambda value: value[0],
        )
        ordered_ids = [track_id for _, track_id in ordered]

        playlist_id = review.provider_playlist_id
        target_url = review.target_url
        if not playlist_id:
            result = client.create_playlist(
                token,
                review.source_playlist.title,
                ordered_ids,
            )
            playlist_id = str(result["id"])
            target_url = (
                safe_candidate_url(result.get("permalink_url"), "soundcloud")
                or "https://soundcloud.com"
            )
        else:
            client.update_playlist_tracks(token, playlist_id, ordered_ids)
        return playlist_id, target_url

    raise TransferError("Неизвестный целевой музыкальный сервис.")
