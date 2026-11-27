import base64
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from transfer.services.common import TransferError
from transfer.services.provider_catalog_access import get_catalog_access
from transfer.services.soundcloud_client import SoundCloudClient


def identity(value):
    return value


@override_settings(
    SPOTIFY_CLIENT_ID="spotify-app-id",
    SPOTIFY_CLIENT_SECRET="spotify-app-secret",
    SPOTIFY_REDIRECT_URI="https://example.test/spotify/callback/",
    SOUNDCLOUD_CLIENT_ID="soundcloud-app-id",
    SOUNDCLOUD_CLIENT_SECRET="soundcloud-app-secret",
    SOUNDCLOUD_REDIRECT_URI="https://example.test/soundcloud/callback/",
)
class ProviderCatalogAccessTests(SimpleTestCase):
    @patch("transfer.services.provider_catalog_access.encrypt_payload", side_effect=identity)
    @patch("transfer.services.provider_catalog_access.cache")
    @patch("transfer.services.provider_catalog_access.SpotifyClient.client_credentials_token")
    def test_spotify_catalog_search_uses_app_credentials_and_caches_token(
        self, token_request, cache, _encrypt
    ):
        cache.get.return_value = None
        token_request.return_value = {"access_token": "app-token", "expires_in": 3600}

        client, token = get_catalog_access("spotify")

        self.assertEqual(token, "app-token")
        self.assertEqual(client.client_id, "spotify-app-id")
        token_request.assert_called_once_with()
        cache.set.assert_called_once()
        self.assertEqual(cache.set.call_args.kwargs["timeout"], 12 * 60 * 60)

    @patch("transfer.services.provider_catalog_access.encrypt_payload", side_effect=identity)
    @patch("transfer.services.provider_catalog_access.cache")
    @patch("transfer.services.provider_catalog_access.SoundCloudClient.client_credentials_token")
    def test_soundcloud_catalog_search_does_not_require_user_oauth(
        self, token_request, cache, _encrypt
    ):
        cache.get.return_value = None
        token_request.return_value = {
            "access_token": "app-token",
            "refresh_token": "refresh-token",
            "expires_in": 1800,
        }

        client, token = get_catalog_access("soundcloud")

        self.assertEqual(token, "app-token")
        self.assertEqual(client.client_id, "soundcloud-app-id")
        token_request.assert_called_once_with()
        saved = cache.set.call_args.args[1]
        self.assertEqual(saved["refresh_token"], "refresh-token")

    @patch("transfer.services.provider_catalog_access.encrypt_payload", side_effect=identity)
    @patch("transfer.services.provider_catalog_access.decrypt_payload", side_effect=identity)
    @patch("transfer.services.provider_catalog_access.cache")
    @patch("transfer.services.provider_catalog_access.SoundCloudClient.refresh_token")
    def test_soundcloud_cached_refresh_token_is_rotated(
        self, refresh, cache, _decrypt, _encrypt
    ):
        cache.get.return_value = {
            "access_token": "expired-token",
            "refresh_token": "single-use-refresh",
            "expires_at": 1,
        }
        refresh.return_value = {
            "access_token": "renewed-token",
            "refresh_token": "rotated-refresh",
            "expires_in": 3600,
        }

        _client, token = get_catalog_access("soundcloud")

        self.assertEqual(token, "renewed-token")
        refresh.assert_called_once_with("single-use-refresh")
        saved = cache.set.call_args.args[1]
        self.assertEqual(saved["refresh_token"], "rotated-refresh")

    def test_soundcloud_client_credentials_token_uses_http_basic(self):
        client = SoundCloudClient(
            "soundcloud-app-id",
            "soundcloud-app-secret",
            "https://example.test/soundcloud/callback/",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"access_token": "app-token", "expires_in": 3600}
        client.http.post = Mock(return_value=response)

        result = client.client_credentials_token()

        self.assertEqual(result["access_token"], "app-token")
        kwargs = client.http.post.call_args.kwargs
        self.assertEqual(kwargs["data"], {"grant_type": "client_credentials"})
        expected = base64.b64encode(
            b"soundcloud-app-id:soundcloud-app-secret"
        ).decode()
        self.assertEqual(kwargs["headers"]["Authorization"], f"Basic {expected}")

    @override_settings(SPOTIFY_CLIENT_ID="", SPOTIFY_CLIENT_SECRET="")
    def test_missing_app_credentials_explain_user_oauth_is_not_required(self):
        with self.assertRaisesRegex(
            TransferError, "Пользовательское подключение не требуется"
        ):
            get_catalog_access("spotify")

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(TransferError):
            get_catalog_access("youtube_music")
