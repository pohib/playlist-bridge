"""Compatibility facade for provider-specific library import services."""

from .library_import_soundcloud import (
    save_soundcloud_playlist,
    validate_soundcloud_permalink,
)
from .library_import_spotify import save_spotify_playlist, spotify_resource_id
from .library_import_vk import (
    refresh_vk_track_metadata,
    save_vk_playlist,
    save_vk_track,
)

__all__ = [
    "refresh_vk_track_metadata",
    "save_soundcloud_playlist",
    "save_spotify_playlist",
    "save_vk_playlist",
    "save_vk_track",
    "spotify_resource_id",
    "validate_soundcloud_permalink",
]
