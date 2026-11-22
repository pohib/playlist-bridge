from django.test import TestCase, override_settings
from django.urls import reverse
from .core import parse_vk_playlist_url, normalize_track_text

class InputValidationTests(TestCase):
    def test_vk_playlist_url_parsed(self):
        self.assertEqual(parse_vk_playlist_url("https://vk.ru/music/playlist/241688629_5_abcd"), (241688629, 5, "abcd"))
    def test_foreign_host_rejected(self):
        with self.assertRaises(ValueError):
            parse_vk_playlist_url("https://evil.example/music/playlist/1_2_key")
    def test_invalid_url_rejected(self):
        with self.assertRaises(ValueError):
            parse_vk_playlist_url("javascript:alert(1)")
    def test_normalization(self):
        self.assertEqual(normalize_track_text("Ёлка — Прованс!"), "елка прованс")

class HttpSurfaceTests(TestCase):
    def test_home(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
    def test_health(self):
        self.assertEqual(self.client.get(reverse("healthz")).json(), {"status": "ok"})
    def test_transfer_requires_post(self):
        self.assertEqual(self.client.get(reverse("transfer_playlist")).status_code, 405)
