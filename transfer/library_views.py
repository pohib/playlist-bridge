"""Compatibility facade for library views.

Concrete handlers live in focused modules; keep these re-exports so existing
URL names and third-party imports remain stable.
"""

from .library_local_playback_views import stream_local_track  # noqa: F401
from .library_management_views import (
    _normalized_track_key,  # noqa: F401
    _safe_optional_url,  # noqa: F401
    add_track,  # noqa: F401
    create_playlist,  # noqa: F401
    delete_playlist,  # noqa: F401
    delete_track,  # noqa: F401
    merge_playlists,  # noqa: F401
    update_profile,  # noqa: F401
    upload_local_track,  # noqa: F401
)
from .library_provider_upload_views import upload_track_to_soundcloud  # noqa: F401
from .library_search_views import (
    open_playlist_source,  # noqa: F401
    open_track_source,  # noqa: F401
    search_library_sources,  # noqa: F401
)
from .library_soundcloud_import_views import (
    _save_soundcloud_playlist,  # noqa: F401
    _validate_soundcloud_permalink,  # noqa: F401
    import_soundcloud_library,  # noqa: F401
    import_soundcloud_playlist,  # noqa: F401
    import_soundcloud_track,  # noqa: F401
)
from .library_spotify_import_views import (
    _save_spotify_playlist,  # noqa: F401
    _spotify_resource_id,  # noqa: F401
    import_spotify_library,  # noqa: F401
    import_spotify_playlist,  # noqa: F401
    import_spotify_track,  # noqa: F401
)
from .library_support import (
    _profile,  # noqa: F401
    _safe_candidate_url,  # noqa: F401
    _soundcloud_access,  # noqa: F401
    _spotify_access,  # noqa: F401
)
from .library_transfer_views import (
    open_transfer_candidate,  # noqa: F401
    open_transfer_target,  # noqa: F401
    search_transfer_item,  # noqa: F401
    select_transfer_candidate,  # noqa: F401
    skip_transfer_item,  # noqa: F401
    transfer_library_playlist,  # noqa: F401
    transfer_review,  # noqa: F401
)
from .library_vk_import_views import (
    import_vk_playlist,  # noqa: F401
    import_vk_track,  # noqa: F401
    refresh_vk_artwork,  # noqa: F401
)
from .library_vk_playback_views import (
    get_vk_track_stream,  # noqa: F401
    stream_vk_track_audio,  # noqa: F401
)

from .services.audio_file_validation import (
    has_audio_file_signature as _has_audio_file_signature,  # noqa: F401
)
