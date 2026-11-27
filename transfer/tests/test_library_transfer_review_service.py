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
from transfer.services.library_transfer_review import (
    select_transfer_candidate,
    skip_transfer_item,
)


class LibraryTransferReviewServiceTests(TestCase):
    def setUp(self):
        self.profile = LibraryProfile.objects.create(session_fingerprint="v" * 64)
        self.other_profile = LibraryProfile.objects.create(session_fingerprint="w" * 64)
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
            duration_ms=120000,
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
            candidates=[{
                "id": "A" * 22,
                "uri": "spotify:track:" + "A" * 22,
                "title": "Track",
                "url": "https://open.spotify.com/track/" + "A" * 22,
            }],
        )
        self.spotify = Mock()
        self.spotify.create_playlist.return_value = "new-playlist"
        self.safe_url = lambda value, provider: (
            value if isinstance(value, str) and value.startswith("https://") else ""
        )

    def _select(self, *, profile=None, candidate_id=None, spotify=None):
        return select_transfer_candidate(
            profile=profile or self.profile,
            transfer_id=self.review.pk,
            item_id=self.item.pk,
            candidate_id=candidate_id or "A" * 22,
            spotify_access=lambda: (spotify or self.spotify, "token"),
            soundcloud_access=Mock(),
            safe_candidate_url=self.safe_url,
        )

    def test_selection_updates_provider_and_local_review_state(self):
        review, item, candidate = self._select()

        self.assertEqual(candidate["id"], "A" * 22)
        self.assertEqual(review.provider_playlist_id, "new-playlist")
        self.assertEqual(review.matched, 1)
        self.assertEqual(item.status, LibraryTransferItem.Status.MATCHED)
        self.assertEqual(item.target_external_id, "A" * 22)
        self.assertEqual(review.status, LibraryTransfer.Status.COMPLETED)
        self.spotify.create_playlist.assert_called_once_with("token", "Source")
        self.spotify.add_items.assert_called_once_with(
            "token",
            "new-playlist",
            ["spotify:track:" + "A" * 22],
        )
        local_track = LibraryTrack.objects.get(playlist=self.target)
        self.assertEqual(local_track.external_id, "A" * 22)
        self.assertEqual(local_track.position, 0)

    def test_selection_rejects_another_profiles_transfer(self):
        with self.assertRaises(TransferError):
            self._select(profile=self.other_profile)

        self.spotify.create_playlist.assert_not_called()
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, LibraryTransferItem.Status.PENDING)

    def test_selection_rejects_candidate_not_returned_by_search(self):
        with self.assertRaises(TransferError):
            self._select(candidate_id="not-a-candidate")

        self.spotify.create_playlist.assert_not_called()
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, LibraryTransferItem.Status.PENDING)

    def test_selection_rejects_later_pending_item(self):
        self.item.position = 1
        self.item.save(update_fields=["position"])
        earlier_track = LibraryTrack.objects.create(
            playlist=self.source,
            title="Earlier",
            artist="Artist",
            position=1,
        )
        LibraryTransferItem.objects.create(
            transfer=self.review,
            source_track=earlier_track,
            position=0,
        )

        with self.assertRaises(TransferError):
            self._select()

        self.spotify.create_playlist.assert_not_called()

    def test_skip_marks_last_item_and_completes_review(self):
        review, item = skip_transfer_item(
            profile=self.profile,
            transfer_id=self.review.pk,
            item_id=self.item.pk,
        )

        self.assertEqual(item.status, LibraryTransferItem.Status.SKIPPED)
        self.assertEqual(review.skipped, 1)
        self.assertEqual(review.status, LibraryTransfer.Status.COMPLETED)
        self.assertIsNotNone(review.completed_at)

    def test_skip_rejects_another_profiles_transfer(self):
        with self.assertRaises(TransferError):
            skip_transfer_item(
                profile=self.other_profile,
                transfer_id=self.review.pk,
                item_id=self.item.pk,
            )

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, LibraryTransferItem.Status.PENDING)
