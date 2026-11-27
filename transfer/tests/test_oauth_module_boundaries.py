from django.test import SimpleTestCase
from django.urls import resolve, reverse

from transfer import oauth_views
from transfer.oauth import clients, shared, soundcloud, spotify


class OAuthModuleBoundaryTests(SimpleTestCase):
    def test_legacy_facade_reexports_shared_helpers_and_client_factories(self):
        self.assertIs(oauth_views.encryption_key_is_valid, shared.encryption_key_is_valid)
        self.assertIs(oauth_views.rotate_session_binding, shared.rotate_session_binding)
        self.assertIs(oauth_views.connected_providers, shared.connected_providers)
        self.assertIs(oauth_views.spotify_client, clients.spotify_client)
        self.assertIs(oauth_views.soundcloud_client, clients.soundcloud_client)

    def test_provider_flows_are_split_into_independent_modules(self):
        for flow in (spotify, soundcloud):
            with self.subTest(provider=flow.__name__):
                self.assertTrue(callable(flow.login))
                self.assertTrue(callable(flow.callback))
                self.assertTrue(callable(flow.disconnect))

    def test_existing_oauth_routes_keep_the_legacy_facade_and_names(self):
        expected = {
            "spotify_login": oauth_views.spotify_login,
            "spotify_callback": oauth_views.spotify_callback,
            "disconnect_spotify": oauth_views.disconnect_spotify,
            "soundcloud_login": oauth_views.soundcloud_login,
            "soundcloud_callback": oauth_views.soundcloud_callback,
            "disconnect_soundcloud": oauth_views.disconnect_soundcloud,
        }
        for route_name, view in expected.items():
            with self.subTest(route_name=route_name):
                self.assertEqual(resolve(reverse(route_name)).func, view)
