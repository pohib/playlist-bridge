# ruff: noqa: I001
"""Orchestration for importing a VK playlist into Spotify."""
import re
from urllib.parse import urlparse

from .common import TransferError
from .track_matcher import score_candidate
from .vk_client import VKClient

def execute_transfer(
    *, vk_version, spotify, spotify_token, source_url, target_playlist=None,
    progress_callback=None, token_provider=None,
):
    playlist_name, tracks = VKClient(version=vk_version).fetch_playlist(source_url)
    if token_provider:
        spotify_token = token_provider()
    user = spotify.current_user(spotify_token)
    if target_playlist:
        parsed = urlparse(target_playlist) if "://" in target_playlist else None
        if parsed:
            parts = [part for part in parsed.path.split("/") if part]
            if parsed.hostname not in {"open.spotify.com", "www.open.spotify.com"} or len(parts) < 2 or parts[-2] != "playlist":
                raise TransferError("Укажи корректную ссылку на плейлист Spotify.")
            target_playlist = parts[-1]
        if not re.fullmatch(r"[A-Za-z0-9]{22}", target_playlist):
            raise TransferError("ID плейлиста Spotify имеет неверный формат.")
        spotify.verify_playlist_access(spotify_token, target_playlist, user.get("id"))

    uris, report = [], []
    total = len(tracks)
    for index, track in enumerate(tracks, 1):
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
            uris.append(selected["uri"])
        report.append({
            "index": index, "artist": track.artist, "title": track.title, "status": status,
            "spotify_name": selected.get("name", "") if selected else "", "score": round(score, 3),
        })
        if progress_callback:
            progress_callback({
                "progress": min(99, int(index * 100 / total)),
                "total": total,
                "matched": len(uris),
                "not_found": sum(row["status"] == "not_found" for row in report),
                "ambiguous": sum(row["status"] == "ambiguous" for row in report),
            })

    if not uris:
        raise TransferError("Не удалось подобрать ни одной композиции. Плейлист Spotify не создавался.")
    if token_provider:
        spotify_token = token_provider()
    if not target_playlist:
        target_playlist = spotify.create_playlist(spotify_token, playlist_name)
    spotify.add_items(spotify_token, target_playlist, uris)
    return {
        "playlist_name": playlist_name, "target_playlist_id": target_playlist, "total": total,
        "matched": len(uris), "not_found": sum(x["status"] == "not_found" for x in report),
        "ambiguous": sum(x["status"] == "ambiguous" for x in report), "report": report,
    }
