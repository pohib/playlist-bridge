"""VK stream resolution and bounded upstream audio connection."""

import logging
import re
import time

import requests

from .common import TransferError

logger = logging.getLogger(__name__)


class VKPlaybackError(Exception):
    """Expected, safe-to-return failure while resolving a VK audio stream."""

    def __init__(self, message, status_code=422):
        super().__init__(message)
        self.status_code = status_code


def resolve_vk_track_stream(api, playlist, external_id, stream_format):
    """Resolve playlist-local IDs and request a fresh short-lived VK stream URL."""
    audio_id = external_id
    if (
        re.fullmatch(r"-?\d+_\d+", audio_id)
        and "/music/playlist/" in playlist.external_url
    ):
        try:
            audio_id = api.resolve_playlist_audio_id(playlist.external_url, audio_id)
        except (ValueError, TransferError) as exc:
            raise VKPlaybackError(str(exc)) from exc

    last_error = None
    for attempt in range(2):
        try:
            return api.get_track_stream(audio_id, stream_format)
        except TransferError as exc:
            last_error = exc
            if "ограничение доступа" in str(exc).lower() or "не предоставил" in str(exc).lower():
                break
            if attempt == 0:
                time.sleep(0.35)
    raise VKPlaybackError(
        str(last_error or "VK временно не выдал аудиопоток.")
    ) from last_error


def open_vk_track_audio(api, playlist, external_id, range_header=""):
    """Open a fresh MP3 upstream response and validate its Range semantics."""
    stream = resolve_vk_track_stream(api, playlist, external_id, "mp3")
    headers = {
        **api.token_provider.BROWSER_HEADERS,
        "Accept": "audio/mpeg,audio/*;q=0.9,*/*;q=0.8",
        "Referer": api.token_provider.referer,
    }
    if range_header:
        headers["Range"] = range_header
    try:
        upstream = requests.get(
            stream["url"],
            headers=headers,
            stream=True,
            timeout=(8, 45),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        logger.exception("VK CDN stream request failed")
        raise VKPlaybackError(
            "Не удалось подключиться к CDN VK. Попробуй запустить трек ещё раз.",
            502,
        ) from exc

    if upstream.status_code not in {200, 206}:
        upstream.close()
        raise VKPlaybackError("VK CDN не смог отдать аудиопоток.", 502)
    if upstream.status_code == 206 and not upstream.headers.get("Content-Range"):
        upstream.close()
        raise VKPlaybackError("VK CDN вернул некорректный диапазон аудио.", 502)
    return upstream
