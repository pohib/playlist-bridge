from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from transfer.services.library_transfer_matching import (
    MATCH_THRESHOLD,
    REVIEW_THRESHOLD,
    match_soundcloud_tracks,
    match_spotify_tracks,
)


class LibraryTransferMatchingTests(SimpleTestCase):
    def setUp(self):
        self.track = SimpleNamespace(
            pk="track-1", title="Midnight City", artist="M83", duration_ms=243000,
        )
        self.safe_url = Mock(side_effect=lambda value, provider: value if value.startswith("https://") else "")

    def test_spotify_confident_match_is_returned_separately_from_review(self):
        candidate = {
            "id": "A" * 22,
            "uri": "spotify:track:" + "A" * 22,
            "name": "Midnight City",
            "artists": [{"name": "M83"}],
            "duration_ms": 243000,
            "external_urls": {"spotify": "https://open.spotify.com/track/" + "A" * 22},
        }
        client = Mock()
        client.search.return_value = [candidate]

        matched, unmatched = match_spotify_tracks(
            [self.track], client=client, token="token", safe_candidate_url=self.safe_url,
        )

        self.assertEqual(matched[self.track.pk]["id"], "A" * 22)
        self.assertEqual(unmatched, [])
        client.search.assert_called_once_with("token", "M83", "Midnight City")

    def test_spotify_low_confidence_candidate_is_kept_for_manual_review(self):
        candidate = {
            "id": "B" * 22,
            "uri": "spotify:track:" + "B" * 22,
            "name": "Midnight City Extended",
            "artists": [{"name": "M83"}],
            "duration_ms": 1000,
            "external_urls": {"spotify": "https://open.spotify.com/track/" + "B" * 22},
        }
        client = Mock()
        client.search.return_value = [candidate]

        matched, unmatched = match_spotify_tracks(
            [self.track], client=client, token="token", safe_candidate_url=self.safe_url,
        )

        self.assertEqual(matched, {})
        self.assertEqual(unmatched[0][0], self.track)
        self.assertEqual(unmatched[0][1][0]["id"], "B" * 22)

    def test_spotify_rejects_invalid_track_uri_even_with_matching_metadata(self):
        candidate = {
            "id": "A" * 22, "uri": "spotify:album:" + "A" * 22,
            "name": "Midnight City", "artists": [{"name": "M83"}], "duration_ms": 243000,
        }
        client = Mock()
        client.search.return_value = [candidate]

        matched, unmatched = match_spotify_tracks(
            [self.track], client=client, token="token", safe_candidate_url=self.safe_url,
        )

        self.assertEqual(matched, {})
        self.assertEqual(unmatched, [(self.track, [])])

    def test_soundcloud_confident_match_uses_artist_and_duration(self):
        candidate = {
            "id": 12345, "title": "Midnight City", "metadata_artist": "M83",
            "duration": 243000, "permalink_url": "https://soundcloud.com/m83/midnight-city",
        }
        client = Mock()
        client.search_tracks.return_value = [candidate]

        matched, unmatched = match_soundcloud_tracks(
            [self.track], client=client, token="token", safe_candidate_url=self.safe_url,
        )

        self.assertEqual(matched[self.track.pk]["id"], "12345")
        self.assertEqual(unmatched, [])
        client.search_tracks.assert_called_once_with("token", "M83 Midnight City")

    def test_soundcloud_review_candidates_are_capped_and_validated(self):
        candidates = [
            {
                "id": index, "title": "Midnight City Extended", "metadata_artist": "M83",
                "duration": 500000, "permalink_url": f"https://soundcloud.com/m83/{index}",
            }
            for index in range(1, 9)
        ]
        client = Mock()
        client.search_tracks.return_value = candidates

        matched, unmatched = match_soundcloud_tracks(
            [self.track], client=client, token="token", safe_candidate_url=self.safe_url,
        )

        self.assertEqual(matched, {})
        self.assertLessEqual(len(unmatched[0][1]), 5)
        self.assertEqual(len(unmatched[0][1]), 5)
        self.assertGreaterEqual(MATCH_THRESHOLD, REVIEW_THRESHOLD)
