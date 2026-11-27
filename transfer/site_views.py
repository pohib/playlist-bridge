"""Compatibility exports for the split site page views."""

from .account_page_views import connections, player_popout, profile, transfers
from .dashboard_views import dashboard
from .library_page_views import library, playlist_detail
from .views import home as landing

__all__ = [
    "connections",
    "dashboard",
    "landing",
    "library",
    "player_popout",
    "playlist_detail",
    "profile",
    "transfers",
]
