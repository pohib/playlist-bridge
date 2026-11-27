from django.test import SimpleTestCase

from transfer.services.library_source_links import (
    safe_provider_candidate_url,
    safe_provider_source_url,
)


class SafeProviderSourceURLTests(SimpleTestCase):
    def test_accepts_supported_https_provider_hosts(self):
        cases = (
            ("https://vk.ru/audio123", "vk"),
            ("https://open.spotify.com/track/abc", "spotify"),
            ("https://m.soundcloud.com/artist/track", "soundcloud"),
            ("https://music.youtube.com/watch?v=abc", "youtube_music"),
            ("https://music.apple.com/album/example", "apple_music"),
        )

        for value, provider in cases:
            with self.subTest(provider=provider):
                self.assertEqual(safe_provider_source_url(value, provider), value)

    def test_accepts_default_https_port_only(self):
        value = "https://open.spotify.com:443/track/abc"

        self.assertEqual(safe_provider_source_url(value, "spotify"), value)

    def test_rejects_untrusted_origins_and_unsafe_url_components(self):
        cases = (
            ("http://open.spotify.com/track/abc", "spotify"),
            ("https://open.spotify.com.attacker.example/track/abc", "spotify"),
            ("https://attacker-open.spotify.com/track/abc", "spotify"),
            ("https://user:pass@open.spotify.com/track/abc", "spotify"),
            ("https://open.spotify.com:8443/track/abc", "spotify"),
            ("https://open.spotify.com:invalid/track/abc", "spotify"),
            ("https://open.spotify.com/track/abc", "unknown"),
        )

        for value, provider in cases:
            with self.subTest(value=value, provider=provider):
                self.assertEqual(safe_provider_source_url(value, provider), "")

    def test_rejects_empty_non_string_and_oversized_values(self):
        for value in (None, "", 123, "https://open.spotify.com/" + "a" * 2048):
            with self.subTest(value=type(value).__name__):
                self.assertEqual(safe_provider_source_url(value, "spotify"), "")


class SafeProviderCandidateURLTests(SimpleTestCase):
    def test_candidate_urls_trim_surrounding_whitespace(self):
        value = "  https://open.spotify.com/track/abc  "

        self.assertEqual(
            safe_provider_candidate_url(value, "spotify"),
            "https://open.spotify.com/track/abc",
        )

    def test_candidate_urls_reject_untrusted_hosts(self):
        self.assertEqual(
            safe_provider_candidate_url(
                " https://open.spotify.com.attacker.example/track/abc ",
                "spotify",
            ),
            "",
        )

    def test_candidate_urls_reject_non_string_values(self):
        self.assertEqual(safe_provider_candidate_url(None, "spotify"), "")
