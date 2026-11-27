"""Resumable orchestration for importing a VK playlist into Spotify."""
import re
from collections import Counter
from urllib.parse import urlparse

from .common import TransferError
from .track_matcher import score_candidate
from .vk_client import VKClient


def _playlist_track_uri(item):
    """Extract a Spotify URI from playlist-item response variants."""
    if not isinstance(item, dict):
        return None
    track = item.get("track") or item.get("item") or item
    if not isinstance(track, dict):
        return None
    uri = track.get("uri")
    return uri if isinstance(uri, str) and re.fullmatch(
        r"spotify:track:[A-Za-z0-9]{22}", uri
    ) else None


def _normalize_counts(value):
    if not isinstance(value, dict):
        return None
    counts = {}
    for uri, count in value.items():
        if (
            isinstance(uri, str)
            and re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", uri)
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count >= 0
        ):
            counts[uri] = count
        else:
            return None
    return counts


def execute_transfer(
    *, vk_version, spotify, spotify_token, source_url, target_playlist=None,
    progress_callback=None, token_provider=None, checkpoint=None,
    checkpoint_callback=None,
):
    checkpoint = dict(checkpoint or {})
    playlist_name, tracks = VKClient(version=vk_version).fetch_playlist(source_url)
    if token_provider:
        spotify_token = token_provider()
    user = spotify.current_user(spotify_token)

    if checkpoint.get("source_track_count") not in (None, len(tracks)):
        raise TransferError(
            "Исходный плейлист изменился после прерывания. Создай новый перенос."
        )

    saved_target = checkpoint.get("target_playlist_id")
    if saved_target:
        target_playlist = saved_target
    if target_playlist:
        parsed = urlparse(target_playlist) if "://" in target_playlist else None
        if parsed:
            parts = [part for part in parsed.path.split("/") if part]
            if parsed.hostname not in {"open.spotify.com", "www.open.spotify.com"} or len(parts) < 2 or parts[-2] != "playlist":
                raise TransferError("Укажи корректную ссылку на плейлист Spotify.")
            target_playlist = parts[-1]
        if not isinstance(target_playlist, str) or not re.fullmatch(r"[A-Za-z0-9]{22}", target_playlist):
            raise TransferError("ID плейлиста Spotify имеет неверный формат.")
        spotify.verify_playlist_access(spotify_token, target_playlist, user.get("id"))

    report = checkpoint.get("report")
    matched_uris = checkpoint.get("matched_uris")
    if not isinstance(report, list) or not isinstance(matched_uris, list):
        report, matched_uris = [], []
    if len(report) > len(tracks) or len(matched_uris) > len(report):
        raise TransferError("Контрольная точка переноса повреждена. Создай новый перенос.")
    for uri in matched_uris:
        if not isinstance(uri, str) or not re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", uri):
            raise TransferError("Контрольная точка содержит некорректный Spotify URI.")

    total = len(tracks)
    for index in range(len(report), total):
        track = tracks[index]
        if token_provider:
            spotify_token = token_provider()
        ranked = sorted(
            ((score_candidate(track, item), item) for item in spotify.search(spotify_token, track.artist, track.title)),
            key=lambda pair: pair[0], reverse=True,
        )
        if not ranked or ranked[0][0] < .82:
            status, selected, score = "not_found", None, ranked[0][0] if ranked else 0.0
        elif len(ranked) > 1 and ranked[0][0] - ranked[1][0] < .045:
            status, selected, score = "ambiguous", None, ranked[0][0]
        else:
            score, selected = ranked[0]
            status = "matched" if selected.get("uri") else "not_found"
        if status == "matched":
            matched_uris.append(selected["uri"])
        report.append({
            "index": index + 1, "artist": track.artist, "title": track.title, "status": status,
            "spotify_name": selected.get("name", "") if selected else "", "score": round(score, 3),
        })
        checkpoint = {
            "version": 1,
            "source_track_count": total,
            "playlist_name": playlist_name,
            "report": report,
            "matched_uris": matched_uris,
            "target_playlist_id": target_playlist or "",
            "baseline_counts": checkpoint.get("baseline_counts"),
        }
        if checkpoint_callback:
            checkpoint_callback(checkpoint)
        if progress_callback:
            progress_callback({
                "progress": min(90, int((index + 1) * 90 / max(total, 1))),
                "total": total,
                "matched": len(matched_uris),
                "not_found": sum(row["status"] == "not_found" for row in report),
                "ambiguous": sum(row["status"] == "ambiguous" for row in report),
            })

    if not matched_uris:
        raise TransferError("Не удалось подобрать ни одной композиции. Плейлист Spotify не создавался.")

    if token_provider:
        spotify_token = token_provider()
    if not target_playlist:
        checkpoint["playlist_create_pending"] = True
        checkpoint["report"] = report
        checkpoint["matched_uris"] = matched_uris
        checkpoint["playlist_name"] = playlist_name
        checkpoint["source_track_count"] = total
        if checkpoint_callback:
            checkpoint_callback(checkpoint)
        target_playlist = spotify.create_playlist(spotify_token, playlist_name)
        checkpoint["target_playlist_id"] = target_playlist
        checkpoint["playlist_create_pending"] = False
        checkpoint["playlist_name"] = playlist_name
        checkpoint["source_track_count"] = total
        checkpoint["report"] = report
        checkpoint["matched_uris"] = matched_uris
        checkpoint["version"] = 1
        if checkpoint_callback:
            checkpoint_callback(checkpoint)

    baseline_counts = _normalize_counts(checkpoint.get("baseline_counts"))
    if baseline_counts is None:
        existing_items = spotify.get_playlist_items(spotify_token, target_playlist)
        baseline_counts = Counter(
            uri for item in existing_items if (uri := _playlist_track_uri(item))
        )
        checkpoint["baseline_counts"] = dict(baseline_counts)
        checkpoint["target_playlist_id"] = target_playlist
        if checkpoint_callback:
            checkpoint_callback(checkpoint)

    current_items = spotify.get_playlist_items(spotify_token, target_playlist)
    current_counts = Counter(
        uri for item in current_items if (uri := _playlist_track_uri(item))
    )
    added_counts = current_counts - Counter(baseline_counts)
    required_counts = Counter(matched_uris)
    missing_counts = required_counts - added_counts
    remaining = []
    for uri in matched_uris:
        if missing_counts[uri] > 0:
            remaining.append(uri)
            missing_counts[uri] -= 1
    if remaining:
        if token_provider:
            spotify_token = token_provider()
        spotify.add_items(spotify_token, target_playlist, remaining)

    result = {
        "playlist_name": playlist_name, "target_playlist_id": target_playlist, "total": total,
        "matched": len(matched_uris), "not_found": sum(x["status"] == "not_found" for x in report),
        "ambiguous": sum(x["status"] == "ambiguous" for x in report), "report": report,
    }
    if checkpoint_callback:
        checkpoint_callback({
            **checkpoint,
            "target_playlist_id": target_playlist,
            "baseline_counts": dict(baseline_counts),
            "completed": True,
        })
    return result
