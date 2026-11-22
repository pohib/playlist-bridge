# ruff: noqa: I001
"""Backward-compatible imports; new code should use transfer.services."""
from .services import (
    ReauthorizationRequired, SoundCloudClient, SpotifyClient, TransferError,
    VKClient, VKIDClient, VKTrack, execute_transfer, normalize_track_text,
    parse_vk_playlist_url, parse_vk_track_url, score_candidate,
)

__all__ = [
    "ReauthorizationRequired", "SoundCloudClient", "SpotifyClient",
    "TransferError", "VKClient", "VKIDClient", "VKTrack",
    "execute_transfer", "normalize_track_text", "parse_vk_playlist_url",
    "parse_vk_track_url", "score_candidate",
]
