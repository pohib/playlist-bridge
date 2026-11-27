"""Compatibility exports for library playback endpoints.

Local-file playback and VK streaming are implemented in separate modules.
"""

from .library_local_playback_views import stream_local_track  # noqa: F401
from .library_vk_playback_views import (  # noqa: F401
    get_vk_track_stream,
    stream_vk_track_audio,
)
