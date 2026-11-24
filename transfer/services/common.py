# ruff: noqa: I001
"""Shared provider errors, data structures and URL parsers."""
from dataclasses import dataclass
import re
from urllib.parse import urlparse

class TransferError(Exception):
    """Expected, user-safe transfer error."""


class ReauthorizationRequired(TransferError):
    """The stored provider authorization can no longer be refreshed."""


@dataclass(frozen=True)
class VKTrack:
    owner_id: int
    track_id: int
    artist: str
    title: str
    duration: int
    cover_url: str = ""
    audio_id: str = ""


def _validated_vk_url(value, error_message):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError(error_message)
    parsed = urlparse(value.strip())
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(error_message) from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"vk.ru", "vk.com", "www.vk.com", "m.vk.com"}
        or port not in (None, 80, 443)
        or parsed.username
        or parsed.password
    ):
        raise ValueError(error_message)
    return parsed


def parse_vk_playlist_url(value):
    parsed = _validated_vk_url(value, "Укажи ссылку на плейлист VK.")
    match = re.fullmatch(r"/music/playlist/(-?\d+)_(\d+)(?:_([A-Za-z0-9]+))?/?", parsed.path)
    if not match:
        raise ValueError("Формат ссылки на плейлист VK не распознан.")
    owner, playlist, key = match.groups()
    return int(owner), int(playlist), key or ""


def parse_vk_track_url(value):
    parsed = _validated_vk_url(value, "Укажи ссылку на аудиозапись VK.")
    match = re.fullmatch(r"/audio(-?\d+)_(\d+)/?", parsed.path)
    if not match:
        raise ValueError("Формат ссылки на аудиозапись VK не распознан.")
    return int(match.group(1)), int(match.group(2))

def normalize_track_text(value):
    value = (value or "").casefold().replace("ё", "е")
    value = re.sub(r"\([^)]*(?:remaster|ремастер|version|версия|feat\.?)[^)]*\)", " ", value)
    value = re.sub(r"\[[^]]*\]", " ", value)
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())
