from django.test import SimpleTestCase
from django.urls import resolve, reverse


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
