"""Compatibility facade for shared library view helpers."""

from .services.library_request_context import get_request_profile as _profile
from .services.library_request_context import get_soundcloud_access as _soundcloud_access
from .services.library_request_context import get_spotify_access as _spotify_access
from .services.library_source_links import safe_provider_candidate_url as _safe_candidate_url

__all__ = [
    "_profile",
    "_safe_candidate_url",
    "_soundcloud_access",
    "_spotify_access",
]
