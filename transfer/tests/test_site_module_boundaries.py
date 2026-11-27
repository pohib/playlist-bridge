from django.test import SimpleTestCase
from django.urls import resolve, reverse

from transfer import (
    account_page_views,
    dashboard_views,
    landing_views,
    library_page_views,
    library_playlist_management_views,
    library_profile_management_views,
    library_support,
    library_track_management_views,
    library_vk_playback_views,
    site_views,
    system_views,
    views,
)
from transfer.services import (
    library_request_context,
    library_source_links,
    vk_anonymous_token,
    vk_client,
)


class SitePageModuleBoundaryTests(SimpleTestCase):
    def test_site_routes_resolve_to_page_specific_modules(self):
        expected = {
            "home": ("transfer.landing_views", {}),
            "healthz": ("transfer.system_views", {}),
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
        self.assertIs(views.home, landing_views.home)
        self.assertIs(views.healthz, system_views.healthz)
        expected = {
            "landing": views.home,
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


class LibraryManagementModuleBoundaryTests(SimpleTestCase):
    def test_management_routes_resolve_to_focused_modules(self):
        expected = {
            "library_create_playlist": ("transfer.library_playlist_management_views", {}),
            "library_update_playlist": ("transfer.library_playlist_management_views", {"playlist_id": "00000000-0000-0000-0000-000000000001"}),
            "library_merge_playlists": ("transfer.library_playlist_management_views", {}),
            "library_delete_playlist": ("transfer.library_playlist_management_views", {"playlist_id": "00000000-0000-0000-0000-000000000001"}),
            "library_add_track": ("transfer.library_track_management_views", {"playlist_id": "00000000-0000-0000-0000-000000000001"}),
            "library_move_track": ("transfer.library_track_management_views", {"playlist_id": "00000000-0000-0000-0000-000000000001", "track_id": "00000000-0000-0000-0000-000000000002"}),
            "library_update_track": ("transfer.library_track_management_views", {"playlist_id": "00000000-0000-0000-0000-000000000001", "track_id": "00000000-0000-0000-0000-000000000002"}),
            "library_delete_track": ("transfer.library_track_management_views", {"track_id": "00000000-0000-0000-0000-000000000002"}),
            "library_upload_local_track": ("transfer.library_track_management_views", {}),
            "library_update_profile": ("transfer.library_profile_management_views", {}),
        }
        for route_name, (module_name, kwargs) in expected.items():
            with self.subTest(route_name=route_name):
                url = reverse(route_name, kwargs=kwargs or None)
                self.assertEqual(resolve(url).func.__module__, module_name)

    def test_legacy_management_facade_reexports_handlers(self):
        from transfer import library_management_views

        self.assertIs(library_management_views.create_playlist, library_playlist_management_views.create_playlist)
        self.assertIs(library_management_views.update_playlist, library_playlist_management_views.update_playlist)
        self.assertIs(library_management_views.delete_playlist, library_playlist_management_views.delete_playlist)
        self.assertIs(library_management_views.merge_playlists, library_playlist_management_views.merge_playlists)
        self.assertIs(library_management_views.add_track, library_track_management_views.add_track)
        self.assertIs(library_management_views.update_track, library_track_management_views.update_track)
        self.assertIs(library_management_views.move_track, library_track_management_views.move_track)
        self.assertIs(library_management_views.delete_track, library_track_management_views.delete_track)
        self.assertIs(library_management_views.upload_local_track, library_track_management_views.upload_local_track)
        self.assertIs(library_management_views.update_profile, library_profile_management_views.update_profile)


class VKClientModuleBoundaryTests(SimpleTestCase):
    def test_vk_playback_view_uses_concrete_client_module(self):
        self.assertEqual(
            library_vk_playback_views.VKClient.__module__,
            "transfer.services.vk_client",
        )

    def test_vk_client_reexports_extracted_anonymous_token_provider(self):
        self.assertIs(
            vk_client.VKAnonymousTokenProvider,
            vk_anonymous_token.VKAnonymousTokenProvider,
        )
        self.assertEqual(
            vk_anonymous_token.VKAnonymousTokenProvider.__module__,
            "transfer.services.vk_anonymous_token",
        )
