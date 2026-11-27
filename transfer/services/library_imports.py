"""Compatibility facade for provider-specific library import services."""

from .library_import_soundcloud import (
    import_soundcloud_library,
    save_soundcloud_playlist,
    save_soundcloud_track,
    validate_soundcloud_permalink,
)
from .library_import_spotify import (
    import_spotify_library,
    save_spotify_playlist,
    save_spotify_track,
    spotify_resource_id,
)
from .library_import_vk import (
    refresh_vk_track_metadata,
    save_vk_playlist,
    save_vk_track,
)

__all__ = [
    "import_soundcloud_library",
    "import_spotify_library",
    "refresh_vk_track_metadata",
    "save_soundcloud_playlist",
    "save_soundcloud_track",
    "save_spotify_playlist",
    "save_spotify_track",
    "save_vk_playlist",
    "save_vk_track",
    "spotify_resource_id",
    "validate_soundcloud_permalink",
]
