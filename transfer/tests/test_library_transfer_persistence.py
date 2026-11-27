from unittest.mock import patch

from django.test import TestCase

from transfer.models import (
    LibraryPlaylist,
    LibraryProfile,
    LibraryTrack,
    LibraryTransfer,
    LibraryTransferItem,
)
from transfer.services.library_transfer_persistence import persist_library_transfer


class LibraryTransferPersistenceTests(TestCase):
    def setUp(self):
        self.profile = LibraryProfile.objects.create(session_fingerprint="p" * 64)
        self.source = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Source mix",
            provider=LibraryPlaylist.Provider.VK,
        )
        self.first = LibraryTrack.objects.create(
            playlist=self.source,
            title="Matched",
            artist="Artist",
            position=0,
        )
        self.second = LibraryTrack.objects.create(
            playlist=self.source,
            title="Pending",
            artist="Artist",
            position=1,
        )

    def test_persists_matched_tracks_and_pending_candidates_in_source_order(self):
        candidate = {"id": "candidate-2", "title": "Pending"}
        review = persist_library_transfer(
            playlist=self.source,
            target_provider=LibraryPlaylist.Provider.SPOTIFY,
            tracks=[self.first, self.second],
            matched={
                self.first.pk: {
                    "id": "remote-1",
                    "url": "https://open.spotify.com/track/remote-1",
                },
            },
            unmatched=[(self.second, [candidate])],
            target_id="remote-playlist",
            target_url="https://open.spotify.com/playlist/remote-playlist",
        )

        self.assertEqual(review.status, LibraryTransfer.Status.REVIEW)
        self.assertEqual(review.total, 2)
        self.assertEqual(review.matched, 1)
        self.assertEqual(review.items.count(), 2)
        matched_item, pending_item = list(review.items.order_by("position"))
        self.assertEqual(matched_item.status, LibraryTransferItem.Status.MATCHED)
        self.assertEqual(matched_item.target_external_id, "remote-1")
        self.assertEqual(pending_item.status, LibraryTransferItem.Status.PENDING)
        self.assertEqual(pending_item.candidates, [candidate])
        self.assertEqual(
            list(review.target_playlist.tracks.values_list("position", flat=True)),
            [0],
        )

    def test_persistence_rolls_back_target_playlist_when_review_items_fail(self):
        before = LibraryPlaylist.objects.count()
        with (
            patch(
                "transfer.services.library_transfer_persistence.LibraryTransferItem.objects.bulk_create",
                side_effect=RuntimeError("database write failed"),
            ),
            self.assertRaisesMessage(RuntimeError, "database write failed"),
        ):
            persist_library_transfer(
                playlist=self.source,
                target_provider=LibraryPlaylist.Provider.SPOTIFY,
                tracks=[self.first],
                matched={},
                unmatched=[(self.first, [])],
                target_id="",
                target_url="",
            )

        self.assertEqual(LibraryPlaylist.objects.count(), before)
        self.assertFalse(LibraryTransfer.objects.exists())
