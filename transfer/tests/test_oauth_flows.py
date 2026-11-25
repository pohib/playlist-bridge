from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse

from ..services import TransferError


class OAuthFlowTests(TestCase):
    def test_spotify_login_saves_state_and_redirects_to_provider(self):
        provider = Mock()
        provider.authorization_url.return_value = "https://accounts.spotify.com/authorize?state=test"

        with patch("transfer.oauth_views.spotify_client", return_value=provider):
            response = self.client.get(reverse("spotify_login"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], provider.authorization_url.return_value)
        self.assertTrue(self.client.session.get("spotify_oauth_state"))
        provider.authorization_url.assert_called_once_with(self.client.session["spotify_oauth_state"])

    def test_spotify_callback_rejects_missing_or_mismatched_state(self):
        session = self.client.session
        session["spotify_oauth_state"] = "expected-state"
        session.save()

        with patch("transfer.oauth_views.spotify_client") as provider:
            response = self.client.get(
                reverse("spotify_callback"),
                {"state": "attacker-state", "code": "authorization-code"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("home"))
        self.assertIn("недействителен", self.client.session["oauth_error"])
        provider.assert_not_called()
        self.assertNotIn("spotify_oauth_state", self.client.session)

    def test_spotify_callback_exchanges_code_and_persists_encrypted_credential(self):
        session = self.client.session
        session["spotify_oauth_state"] = "valid-state"
        session.save()
        provider = Mock()
        provider.exchange_code.return_value = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
        }
        provider.current_user.return_value = {"id": "spotify-user"}

        with (
            patch("transfer.oauth_views.spotify_client", return_value=provider),
            patch("transfer.oauth_views.rotate_session_binding") as rotate,
            patch("transfer.oauth_views.store_credential") as store,
        ):
            response = self.client.get(
                reverse("spotify_callback"),
                {"state": "valid-state", "code": "authorization-code"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("home"))
        provider.exchange_code.assert_called_once_with("authorization-code")
        provider.current_user.assert_called_once_with("access-token")
        rotate.assert_called_once()
        self.assertEqual(store.call_args.args[1:], ("spotify", store.call_args.args[2], "spotify-user"))
        self.assertEqual(store.call_args.args[2]["access_token"], "access-token")
        self.assertIn("obtained_at", store.call_args.args[2])
        self.assertIn("успешно подключён", self.client.session["oauth_success"])

    def test_soundcloud_login_stores_state_and_pkce_verifier(self):
        provider = Mock()
        provider.authorization_url.return_value = "https://secure.soundcloud.com/authorize?state=test"

        with patch("transfer.oauth_views.soundcloud_client", return_value=provider):
            response = self.client.get(reverse("soundcloud_login"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], provider.authorization_url.return_value)
        state = self.client.session["soundcloud_oauth_state"]
        verifier = self.client.session["soundcloud_code_verifier"]
        self.assertTrue(state)
        self.assertTrue(verifier)
        provider.authorization_url.assert_called_once_with(state, verifier)

    def test_soundcloud_callback_rejects_invalid_state_and_consumes_pkce_values(self):
        session = self.client.session
        session["soundcloud_oauth_state"] = "expected-state"
        session["soundcloud_code_verifier"] = "pkce-verifier"
        session.save()

        with patch("transfer.oauth_views.soundcloud_client") as provider:
            response = self.client.get(
                reverse("soundcloud_callback"),
                {"state": "wrong-state", "code": "authorization-code"},
            )

        self.assertEqual(response.status_code, 302)
        provider.assert_not_called()
        self.assertNotIn("soundcloud_oauth_state", self.client.session)
        self.assertNotIn("soundcloud_code_verifier", self.client.session)

    def test_soundcloud_callback_exchanges_code_with_saved_verifier(self):
        session = self.client.session
        session["soundcloud_oauth_state"] = "valid-state"
        session["soundcloud_code_verifier"] = "saved-verifier"
        session.save()
        provider = Mock()
        provider.exchange_code.return_value = {"access_token": "sc-access"}
        provider.current_user.return_value = {"id": 12345}

        with (
            patch("transfer.oauth_views.soundcloud_client", return_value=provider),
            patch("transfer.oauth_views.rotate_session_binding"),
            patch("transfer.oauth_views.store_credential") as store,
        ):
            response = self.client.get(
                reverse("soundcloud_callback"),
                {"state": "valid-state", "code": "sc-code"},
            )

        self.assertEqual(response.status_code, 302)
        provider.exchange_code.assert_called_once_with("sc-code", "saved-verifier")
        provider.current_user.assert_called_once_with("sc-access")
        self.assertEqual(store.call_args.args[1], "soundcloud")
        self.assertEqual(store.call_args.args[2]["access_token"], "sc-access")
        self.assertEqual(store.call_args.args[3], "12345")

    def test_disconnect_spotify_deletes_session_credential(self):
        with patch("transfer.oauth_views.delete_credential") as delete:
            response = self.client.post(reverse("disconnect_spotify"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("home"))
        delete.assert_called_once()
        self.assertEqual(delete.call_args.args[1], "spotify")

    def test_disconnect_soundcloud_deletes_credential_even_if_revocation_fails(self):
        provider = Mock()
        provider.disconnect.side_effect = TransferError("provider unavailable")

        with (
            patch("transfer.oauth_views.soundcloud_client", return_value=provider),
            patch("transfer.oauth_views.get_access_token", return_value=("access-token", {})),
            patch("transfer.oauth_views.delete_credential") as delete,
        ):
            response = self.client.post(reverse("disconnect_soundcloud"))

        self.assertEqual(response.status_code, 302)
        provider.disconnect.assert_called_once_with("access-token")
        delete.assert_called_once()
        self.assertEqual(delete.call_args.args[1], "soundcloud")

    @override_settings(SPOTIFY_CLIENT_ID="", SPOTIFY_CLIENT_SECRET="")
    def test_spotify_client_requires_server_credentials(self):
        from ..oauth_views import spotify_client

        with self.assertRaisesRegex(TransferError, "не настроен"):
            spotify_client()

    @override_settings(SOUNDCLOUD_CLIENT_ID="", SOUNDCLOUD_CLIENT_SECRET="")
    def test_soundcloud_client_requires_server_credentials(self):
        from ..oauth_views import soundcloud_client

        with self.assertRaisesRegex(TransferError, "не настроен"):
            soundcloud_client()
