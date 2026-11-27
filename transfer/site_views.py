"""Compatibility exports for the split site page views."""

from .account_page_views import connections, player_popout, profile, transfers
from .dashboard_views import dashboard
from .library_page_views import library, playlist_detail

__all__ = [
    "connections",
    "dashboard",
    "library",
    "player_popout",
    "playlist_detail",
    "profile",
    "transfers",
]
