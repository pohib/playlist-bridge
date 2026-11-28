from unittest.mock import patch

from django.test import SimpleTestCase

from transfer.services.library_source_search_service import (
    DEFAULT_FREE_PROVIDERS,
    LibrarySourceSearchError,
    parse_library_source_search_request,
    search_library_sources,
)


class LibrarySourceSearchRequestTests(SimpleTestCase):
    def test_auto_selects_only_free_server_side_catalogs(self):
        self.assertEqual(
            parse_library_source_search_request({"title": "Track", "artist": "Artist"}),
            ("Track", "Artist", DEFAULT_FREE_PROVIDERS),
        )
        self.assertEqual(DEFAULT_FREE_PROVIDERS, ["deezer", "itunes", "youtube_music"])

    def test_explicit_free_providers_are_deduplicated(self):
        self.assertEqual(
            parse_library_source_search_request({
                "title": "Track", "artist": "Artist",
                "providers": ["deezer", "deezer", "itunes"],
            }),
            ("Track", "Artist", ["deezer", "itunes"]),
        )

    def test_paid_api_search_providers_are_not_accepted(self):
        for provider in ("spotify", "soundcloud", "apple_music", "vk", "unknown"):
            with self.subTest(provider=provider), self.assertRaises(LibrarySourceSearchError):
                parse_library_source_search_request({
                    "title": "Track", "artist": "Artist", "providers": [provider],
                })

    def test_rejects_invalid_payloads(self):
        for payload in (
            [], {"title": "", "artist": "Artist"},
            {"title": "x" * 181, "artist": "Artist"},
            {"title": "Track", "artist": "Artist", "providers": []},
            {"title": "Track", "artist": "Artist", "providers": ["deezer", 1]},
        ):
            with self.subTest(payload=payload), self.assertRaises(LibrarySourceSearchError):
                parse_library_source_search_request(payload)

    @patch("transfer.services.library_source_search_service.search_free_music_catalogs")
    def test_search_does_not_request_paid_catalog_credentials(self, search):
        search.return_value = ([{
            "provider": "deezer", "title": "Track", "artist": "Artist",
            "url": "https://www.deezer.com/track/1", "playable": False, "search_only": True,
        }], {"deezer": "Найдено: 1"})
        result = search_library_sources("Track", "Artist", ["deezer"])
        self.assertEqual(result["query"], "Artist Track")
        self.assertEqual(result["results"][0]["provider"], "deezer")
        search.assert_called_once_with("Artist Track", ["deezer"])
