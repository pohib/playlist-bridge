from cryptography.fernet import Fernet
from django.test import TestCase, override_settings
from django.urls import reverse
from urllib.parse import parse_qs, urlparse
import base64
import hashlib

from .core import VKIDClient, normalize_track_text, parse_vk_playlist_url
from .credentials import decrypt_payload, store_credential
from .models import OAuthCredential
from .views import csv_safe_cell


class InputValidationTests(TestCase):
    def test_vk_playlist_url_parsed(self):
        self.assertEqual(
            parse_vk_playlist_url("https://vk.ru/music/playlist/241688629_5_abcd"),
            (241688629, 5, "abcd"),
        )

    def test_foreign_host_rejected(self):
        with self.assertRaises(ValueError):
            parse_vk_playlist_url("https://evil.example/music/playlist/1_2_key")

    def test_invalid_url_rejected(self):
        with self.assertRaises(ValueError):
            parse_vk_playlist_url("javascript:alert(1)")

    def test_normalization(self):
        self.assertEqual(normalize_track_text("Ёлка — Прованс!"), "елка прованс")

    def test_csv_formula_is_neutralized(self):
        self.assertEqual(csv_safe_cell("=1+1"), "'=1+1")
        self.assertEqual(csv_safe_cell("Artist - Track"), "Artist - Track")


class HttpSurfaceTests(TestCase):
    @override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
    def test_home(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_health(self):
        self.assertEqual(self.client.get(reverse("healthz")).json(), {"status": "ok"})

    def test_transfer_requires_post(self):
        self.assertEqual(self.client.get(reverse("transfer_playlist")).status_code, 405)


class VersionedApiTests(TestCase):
    def test_openapi_document(self):
        response = self.client.get(reverse("api_openapi"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["openapi"], "3.1.0")

    def test_api_status_contract(self):
        response = self.client.get(reverse("api_status"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("spotify_connected", response.json())
        self.assertEqual(response.json()["api_version"], "1")

    def test_create_transfer_requires_json(self):
        response = self.client.post(reverse("api_create_transfer"), {"source_url": "https://vk.ru/"})
        self.assertEqual(response.status_code, 415)

    def test_create_transfer_rejects_invalid_playlist_url(self):
        response = self.client.post(
            reverse("api_create_transfer"),
            data='{"source_url":"https://attacker.example/music/playlist/1_2"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(
        VK_ID_CLIENT_ID="test-vk-app",
        SPOTIFY_CLIENT_ID="test-client",
        SPOTIFY_CLIENT_SECRET="test-secret",
        TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    def test_create_transfer_requires_spotify_session(self):
        response = self.client.post(
            reverse("api_create_transfer"),
            data='{"source_url":"https://vk.ru/music/playlist/241688629_5"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["message"], "Сначала подключи Spotify.")



class OAuthSecurityTests(TestCase):
    def test_vk_oauth_authorization_uses_pkce_s256(self):
        client = VKIDClient("vk-app-id", "https://example.test/vk/callback/")
        verifier = "a" * 64
        url = client.authorization_url("random-state", verifier)
        params = parse_qs(urlparse(url).query)
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(params["code_challenge"][0], expected)
        self.assertEqual(params["code_challenge_method"][0], "s256")
        self.assertEqual(params["state"][0], "random-state")

    @override_settings(TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_oauth_tokens_are_encrypted_at_rest(self):
        token = {"access_token": "user-access-secret", "refresh_token": "user-refresh-secret"}
        credential = store_credential("a" * 64, "spotify", token, "spotify-user")
        self.assertNotIn("user-access-secret", credential.encrypted_payload)
        self.assertNotIn("user-refresh-secret", credential.encrypted_payload)
        self.assertEqual(decrypt_payload(credential.encrypted_payload)["access_token"], "user-access-secret")
        self.assertEqual(OAuthCredential.objects.count(), 1)

    def test_provider_disconnect_requires_post(self):
        self.assertEqual(self.client.get(reverse("disconnect_spotify")).status_code, 405)
        self.assertEqual(self.client.get(reverse("disconnect_vk")).status_code, 405)
