from django.test import SimpleTestCase
from django.urls import resolve, reverse

from transfer import account_page_views, dashboard_views, library_page_views
from transfer import library_support, site_views
from transfer.services import library_request_context, library_source_links


class SitePageModuleBoundaryTests(SimpleTestCase):
    def test_site_routes_resolve_to_page_specific_modules(self):
        expected = {
            "dashboard": ("transfer.dashboard_views", {}),
            "library": ("transfer.library_page_views", {}),
            "playlist_detail": ("transfer.library_page_views", {"playlist_id": "00000000-0000-0000-0000-000000000001"}),
            "connections": ("transfer.account_page_views", {}),
            "transfers": ("transfer.account_page_views", {}),
            "profile": ("transfer.account_page_views", {}),
            "player_popout": ("transfer.account_page_views", {}),
        }
        for route_name, (module_name, kwargs) in expected.items():
            with self.subTest(route_name=route_name):
                url = reverse(route_name, kwargs=kwargs or None)
                self.assertEqual(resolve(url).func.__module__, module_name)

    def test_legacy_site_facade_reexports_page_handlers(self):
        expected = {
            "dashboard": dashboard_views.dashboard,
            "library": library_page_views.library,
            "playlist_detail": library_page_views.playlist_detail,
            "connections": account_page_views.connections,
            "transfers": account_page_views.transfers,
            "profile": account_page_views.profile,
            "player_popout": account_page_views.player_popout,
        }
        for name, implementation in expected.items():
            with self.subTest(name=name):
                self.assertIs(getattr(site_views, name), implementation)

    def test_library_support_facade_reexports_request_context_helpers(self):
        self.assertIs(library_support._profile, library_request_context.get_request_profile)
        self.assertIs(library_support._soundcloud_access, library_request_context.get_soundcloud_access)
        self.assertIs(library_support._spotify_access, library_request_context.get_spotify_access)
        self.assertIs(
            library_support._safe_candidate_url,
            library_source_links.safe_provider_candidate_url,
        )
