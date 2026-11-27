from unittest.mock import Mock

from django.test import TestCase

from transfer.models import (
    LibraryPlaylist,
    LibraryProfile,
    LibraryTrack,
    LibraryTransfer,
    LibraryTransferItem,
)
from transfer.services import TransferError
from transfer.services.library_transfer_review_search import search_pending_transfer_item


class LibraryTransferReviewSearchTests(TestCase):
    def setUp(self):
        self.profile = LibraryProfile.objects.create(session_fingerprint="s" * 64)
        self.source = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Source",
            provider=LibraryPlaylist.Provider.VK,
        )
        self.target = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Target",
            provider=LibraryPlaylist.Provider.SPOTIFY,
        )
        self.track = LibraryTrack.objects.create(
            playlist=self.source,
            title="Track",
            artist="Artist",
            position=0,
        )
        self.review = LibraryTransfer.objects.create(
            profile=self.profile,
            source_playlist=self.source,
            target_playlist=self.target,
            target_provider=LibraryPlaylist.Provider.SPOTIFY,
            total=1,
        )
        self.item = LibraryTransferItem.objects.create(
            transfer=self.review,
            source_track=self.track,
            position=0,
        )
        self.safe_url = lambda value, provider: (
            value if isinstance(value, str) and value.startswith("https://") else ""
        )

    def test_spotify_search_normalizes_and_persists_candidates(self):
        provider = Mock()
        provider.search_tracks.return_value = [{
            "id": "A" * 22,
            "uri": "spotify:track:" + "A" * 22,
            "name": "Track",
            "artists": [{"name": "Artist"}],
            "duration_ms": 120000,
            "external_urls": {
                "spotify": "https://open.spotify.com/track/" + "A" * 22,
            },
        }]

        review, item, candidates = search_pending_transfer_item(
            profile=self.profile,
            transfer_id=self.review.pk,
            item_id=self.item.pk,
            query="Track",
            spotify_access=lambda: (provider, "token"),
            soundcloud_access=Mock(),
            safe_candidate_url=self.safe_url,
        )

        self.assertEqual(review.pk, self.review.pk)
        self.assertEqual(candidates[0]["id"], "A" * 22)
        self.assertEqual(candidates[0]["artist"], "Artist")
        item.refresh_from_db()
        self.assertEqual(item.candidates, candidates)
        provider.search_tracks.assert_called_once_with("token", "Track")

    def test_search_rejects_later_item_before_provider_access(self):
        self.item.position = 1
        self.item.save(update_fields=["position"])
        earlier_track = LibraryTrack.objects.create(
            playlist=self.source,
            title="Earlier",
            artist="Artist",
            position=1,
        )
        earlier_item = LibraryTransferItem.objects.create(
            transfer=self.review,
            source_track=earlier_track,
            position=0,
        )
        access = Mock()

        with self.assertRaises(TransferError):
            search_pending_transfer_item(
                profile=self.profile,
                transfer_id=self.review.pk,
                item_id=self.item.pk,
                query="Track",
                spotify_access=access,
                soundcloud_access=access,
                safe_candidate_url=self.safe_url,
            )

        access.assert_not_called()
        self.assertEqual(earlier_item.status, LibraryTransferItem.Status.PENDING)

    def test_search_rejects_invalid_query_before_provider_access(self):
        access = Mock()
        with self.assertRaises(TransferError):
            search_pending_transfer_item(
                profile=self.profile,
                transfer_id=self.review.pk,
                item_id=self.item.pk,
                query="x" * 181,
                spotify_access=access,
                soundcloud_access=access,
                safe_candidate_url=self.safe_url,
            )
        access.assert_not_called()
