from django.test import SimpleTestCase

from transfer.services.library_transfer_search import (
    normalize_soundcloud_search_results,
    normalize_spotify_search_results,
)


class LibraryTransferSearchNormalizationTests(SimpleTestCase):
    def setUp(self):
        self.safe_url = lambda value, provider: (
            value if isinstance(value, str) and value.startswith("https://") else ""
        )

    def test_spotify_results_are_normalized_and_invalid_items_are_skipped(self):
        results = [
            None,
            {"id": "missing-uri"},
            {
                "id": "spotify-id",
                "uri": "spotify:track:spotify-id",
                "name": "Track",
                "artists": [{"name": "Artist"}, {"name": "Guest"}],
                "duration_ms": "123000",
                "external_urls": {
                    "spotify": "https://open.spotify.com/track/spotify-id",
                },
            },
        ]

        candidates = normalize_spotify_search_results(results, self.safe_url)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], "spotify-id")
        self.assertEqual(candidates[0]["artist"], "Artist, Guest")
        self.assertEqual(candidates[0]["duration_ms"], 123000)
        self.assertEqual(
            candidates[0]["url"],
            "https://open.spotify.com/track/spotify-id",
        )

    def test_spotify_malformed_nested_fields_and_duration_are_safe(self):
        result = {
            "id": "spotify-id",
            "uri": "spotify:track:spotify-id",
            "artists": "not-a-list",
            "external_urls": [],
            "duration_ms": "invalid",
        }

        candidate = normalize_spotify_search_results(
            [result],
            self.safe_url,
        )[0]

        self.assertEqual(candidate["artist"], "")
        self.assertEqual(candidate["url"], "")
        self.assertEqual(candidate["duration_ms"], 0)

    def test_soundcloud_uses_artist_fallback_and_urn(self):
        result = {
            "id": 123,
            "urn": "soundcloud:tracks:123",
            "title": "Track",
            "user": {"username": "Uploader"},
            "duration": 125000,
            "permalink_url": "https://soundcloud.com/uploader/track",
        }

        candidate = normalize_soundcloud_search_results(
            [result],
            self.safe_url,
        )[0]

        self.assertEqual(candidate["id"], "123")
        self.assertEqual(candidate["uri"], "soundcloud:tracks:123")
        self.assertEqual(candidate["artist"], "Uploader")
        self.assertEqual(candidate["duration_ms"], 125000)

    def test_soundcloud_malformed_duration_and_user_are_safe(self):
        result = {
            "id": 123,
            "title": "Track",
            "user": "invalid",
            "duration": object(),
        }

        candidate = normalize_soundcloud_search_results(
            [result],
            self.safe_url,
        )[0]

        self.assertEqual(candidate["artist"], "")
        self.assertEqual(candidate["duration_ms"], 0)
        self.assertEqual(candidate["url"], "")

    def test_both_providers_cap_manual_review_candidates_at_ten(self):
        spotify = [
            {"id": str(index), "uri": f"spotify:track:{index}"}
            for index in range(12)
        ]
        soundcloud = [{"id": index} for index in range(12)]

        self.assertEqual(
            len(normalize_spotify_search_results(spotify, self.safe_url)),
            10,
        )
        self.assertEqual(
            len(normalize_soundcloud_search_results(soundcloud, self.safe_url)),
            10,
        )
