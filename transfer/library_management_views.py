"""Backward-compatible facade for library management handlers."""

from .library_playlist_management_views import (
    create_playlist,  # noqa: F401
    delete_playlist,  # noqa: F401
    merge_playlists,  # noqa: F401
    update_playlist,  # noqa: F401
)
from .library_profile_management_views import update_profile  # noqa: F401
from .library_track_management_views import (
    add_track,  # noqa: F401
    delete_track,  # noqa: F401
    move_track,  # noqa: F401
    update_track,  # noqa: F401
    upload_local_track,  # noqa: F401
)
from .services.library_management import (
    _normalized_track_key,  # noqa: F401
    _safe_optional_url,  # noqa: F401
)
