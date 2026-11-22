"""Service layer: provider clients, matching and transfer orchestration."""
from .common import (
    ReauthorizationRequired,
    TransferError,
    VKTrack,
    parse_vk_playlist_url,
    parse_vk_track_url,
)
from .soundcloud_client import SoundCloudClient
from .spotify_client import SpotifyClient
from .track_matcher import normalize_track_text, score_candidate
from .transfer_service import execute_transfer
from .vk_client import VKClient, VKIDClient

__all__ = [
    "ReauthorizationRequired", "SoundCloudClient", "SpotifyClient",
    "TransferError", "VKClient", "VKIDClient", "VKTrack",
    "execute_transfer", "normalize_track_text", "parse_vk_playlist_url",
    "parse_vk_track_url", "score_candidate",
]
