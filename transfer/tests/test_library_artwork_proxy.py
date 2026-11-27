from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from transfer.services.library_artwork_proxy import (
    ArtworkProxyError,
    fetch_provider_artwork,
    is_allowed_artwork_url,
)


class ArtworkURLValidationTests(SimpleTestCase):
    def test_allows_known_provider_subdomains(self):
        self.assertTrue(is_allowed_artwork_url("https://images.vk.ru/cover.jpg"))
        self.assertTrue(is_allowed_artwork_url("https://i.scdn.co/image/abc"))

    def test_rejects_untrusted_hosts_and_url_components(self):
        for value in (
            "https://vk.ru.attacker.example/cover.jpg",
            "http://vk.ru/cover.jpg",
            "https://user@vk.ru/cover.jpg",
            "https://vk.ru:8443/cover.jpg",
            "https://attacker.example/cover.jpg",
        ):
            with self.subTest(value=value):
                self.assertFalse(is_allowed_artwork_url(value))


class ProviderArtworkFetchTests(SimpleTestCase):
    def test_fetches_and_detects_png_content(self):
        upstream = Mock(status_code=200, headers={"Content-Length": "12"})
        upstream.iter_content.return_value = [
            bytes.fromhex("89504E470D0A1A0A") + b"data"
        ]
        with patch(
            "transfer.services.library_artwork_proxy.requests.get",
            return_value=upstream,
        ):
            body, content_type = fetch_provider_artwork("https://vk.ru/cover.png")

        self.assertEqual(content_type, "image/png")
        self.assertTrue(body.startswith(bytes.fromhex("89504E470D0A1A0A")))
        upstream.close.assert_called_once()

    def test_rejects_redirect_to_untrusted_host(self):
        upstream = Mock(
            status_code=302,
            headers={"Location": "https://attacker.example/collect"},
        )
        with patch(
            "transfer.services.library_artwork_proxy.requests.get",
            return_value=upstream,
        ) as request:
            with self.assertRaises(ArtworkProxyError) as error:
                fetch_provider_artwork("https://vk.ru/cover.png")

        self.assertEqual(error.exception.status_code, 400)
        upstream.close.assert_called_once()
        request.assert_called_once()

    def test_rejects_non_image_payload(self):
        upstream = Mock(status_code=200, headers={})
        upstream.iter_content.return_value = [b"not an image"]
        with patch(
            "transfer.services.library_artwork_proxy.requests.get",
            return_value=upstream,
        ):
            with self.assertRaisesRegex(ArtworkProxyError, "not a supported image"):
                fetch_provider_artwork("https://vk.ru/cover.png")
        upstream.close.assert_called_once()

    def test_rejects_oversized_content_length_before_reading(self):
        upstream = Mock(
            status_code=200,
            headers={"Content-Length": str(7 * 1024 * 1024)},
        )
        with patch(
            "transfer.services.library_artwork_proxy.requests.get",
            return_value=upstream,
        ):
            with self.assertRaisesRegex(ArtworkProxyError, "too large"):
                fetch_provider_artwork("https://vk.ru/cover.png")
        upstream.close.assert_called_once()
        upstream.iter_content.assert_not_called()

    def test_network_errors_are_normalized(self):
        with patch(
            "transfer.services.library_artwork_proxy.requests.get",
            side_effect=requests.RequestException("private upstream detail"),
        ):
            with self.assertRaisesRegex(ArtworkProxyError, "temporarily unavailable"):
                fetch_provider_artwork("https://vk.ru/cover.png")
