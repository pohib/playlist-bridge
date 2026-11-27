"""Compatibility facade for library management domain services.

Concrete operations live in focused modules. Keep this import surface stable
for existing views, tests and integrations during the decomposition.
"""

from .library_management_errors import LibraryManagementError
from .library_playlist_management import (
    _normalized_track_key,
    _safe_optional_url,
    create_playlist,
    delete_playlist,
    merge_playlists,
)
from .library_profile_management import update_profile
from .library_track_management import add_track, append_provider_track, delete_track
from .library_upload_management import (
    _audio_signature_matches,
    upload_local_track,
)

__all__ = [
    "LibraryManagementError",
    "_audio_signature_matches",
    "_normalized_track_key",
    "_safe_optional_url",
    "add_track",\n    "append_provider_track",
    "create_playlist",
    "delete_playlist",
    "delete_track",
    "merge_playlists",\n    "move_track",\n    "update_playlist",
    "update_profile",
    "upload_local_track",
]
