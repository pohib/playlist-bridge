from django.test import TestCase
from django.urls import get_resolver, reverse
from django.utils.crypto import get_random_string


class UrlContractTests(TestCase):
    def test_named_routes_remain_registered(self):
        expected = {
            "home",
            "register",
            "login",
            "logout",
            "password_change",
            "dashboard",
            "library",
            "library_cover_proxy",
            "playlist_detail",
            "connections",
            "transfers",
            "profile",
            "healthz",
            "spotify_login",
            "spotify_callback",
            "disconnect_spotify",
            "soundcloud_login",
            "soundcloud_callback",
            "disconnect_soundcloud",
            "transfer_playlist",
            "download_report",
            "library_update_profile",
            "library_import_vk",
            "library_import_vk_track",
            "library_refresh_vk_artwork",
            "library_import_spotify_playlist",
            "library_import_spotify_track",
            "library_import_spotify_library",
            "library_import_soundcloud_playlist",
            "library_import_soundcloud_track",
            "library_upload_soundcloud_track",
            "library_import_soundcloud_library",
            "library_transfer_playlist",
            "transfer_review",
            "open_transfer_target",
            "open_transfer_candidate",
            "search_transfer_item",
            "select_transfer_candidate",
            "skip_transfer_item",
            "library_open_playlist_source",
            "library_open_track_source",
            "library_create_playlist",
            "library_merge_playlists",
            "library_upload_local_track",
            "library_stream_local_track",
            "library_add_track",
            "library_delete_playlist",
            "library_delete_track",
            "library_track_search",
            "library_vk_track_stream",
            "library_vk_track_audio",
            "api_status",
            "api_create_transfer",
            "api_transfer_detail",
            "api_transfer_report",
            "api_openapi",
        }
        registered = {
            key for key in get_resolver().reverse_dict
            if isinstance(key, str)
        }

        self.assertTrue(expected.issubset(registered), sorted(expected - registered))

    def test_critical_routes_keep_their_paths(self):
        self.assertEqual(reverse("library"), "/library/")
        self.assertEqual(reverse("library_import_vk"), "/library/import/vk/")
        self.assertEqual(reverse("library_import_spotify_playlist"), "/library/import/spotify/playlist/")
        self.assertEqual(reverse("library_import_soundcloud_playlist"), "/library/import/soundcloud/playlist/")
        self.assertEqual(reverse("api_status"), "/api/v1/status/")
        self.assertEqual(reverse("api_create_transfer"), "/api/v1/transfers/")
        self.assertEqual(reverse("library_track_search"), "/api/v1/library/tracks/search/")

    def test_post_only_import_endpoint_rejects_get(self):
        response = self.client.get(reverse("library_import_vk"))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "POST")

    def test_get_only_audio_endpoint_rejects_post_for_authenticated_user(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(username="route-contract-user", password=get_random_string(32))
        self.client.force_login(user)
        response = self.client.post(
            reverse("library_vk_track_audio", kwargs={"track_id": "00000000-0000-0000-0000-000000000001"})
        )
        self.assertEqual(response.status_code, 405)
        self.assertIn("GET", response["Allow"])
