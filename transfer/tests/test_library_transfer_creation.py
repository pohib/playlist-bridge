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
from transfer.services.library_transfer_creation import create_library_transfer


class LibraryTransferCreationServiceTests(TestCase):
    def setUp(self):
        self.profile = LibraryProfile.objects.create(session_fingerprint="f" * 64)
        self.playlist = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Source mix",
            provider=LibraryPlaylist.Provider.VK,
        )
        self.first = LibraryTrack.objects.create(
            playlist=self.playlist,
            title="Matched track",
            artist="Artist",
            duration_ms=180000,
            position=0,
        )
        self.second = LibraryTrack.objects.create(
            playlist=self.playlist,
            title="Review track",
            artist="Artist",
            duration_ms=190000,
            position=1,
        )
        self.safe_url = lambda value, provider: (
            value if isinstance(value, str) and value.startswith("https://") else ""
        )

    def test_spotify_transfer_persists_matched_and_pending_items(self):
        client = Mock()
        client.search.side_effect = [
            [{
                "id": "A" * 22,
                "uri": "spotify:track:" + "A" * 22,
                "name": "Matched track",
                "artists": [{"name": "Artist"}],
                "duration_ms": 180000,
                "external_urls": {
                    "spotify": "https://open.spotify.com/track/" + "A" * 22,
                },
            }],
            [],
        ]
        client.create_playlist.return_value = "B" * 22

        review, matched, unmatched = create_library_transfer(
            playlist=self.playlist,
            target_provider=LibraryPlaylist.Provider.SPOTIFY,
            tracks=[self.first, self.second],
            client=client,
            token="access-token",
            safe_candidate_url=self.safe_url,
        )

        self.assertEqual(len(matched), 1)
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(review.status, LibraryTransfer.Status.REVIEW)
        self.assertEqual(review.total, 2)
        self.assertEqual(review.matched, 1)
        items = list(review.items.order_by("position"))
        self.assertEqual(
            [item.status for item in items],
            [
                LibraryTransferItem.Status.MATCHED,
                LibraryTransferItem.Status.PENDING,
            ],
        )
        self.assertEqual(items[0].target_external_id, "A" * 22)
        self.assertEqual(review.target_playlist.tracks.get().position, 0)
        client.create_playlist.assert_called_once_with("access-token", "Source mix")
        client.add_items.assert_called_once_with(
            "access-token",
            "B" * 22,
            ["spotify:track:" + "A" * 22],
        )

    def test_soundcloud_transfer_without_matches_does_not_create_remote_playlist(self):
        client = Mock()
        client.search_tracks.return_value = []

        review, matched, unmatched = create_library_transfer(
            playlist=self.playlist,
            target_provider=LibraryPlaylist.Provider.SOUNDCLOUD,
            tracks=[self.first],
            client=client,
            token="access-token",
            safe_candidate_url=self.safe_url,
        )

        self.assertEqual(matched, {})
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(review.status, LibraryTransfer.Status.REVIEW)
        self.assertEqual(review.provider_playlist_id, "")
        self.assertEqual(review.items.get().status, LibraryTransferItem.Status.PENDING)
        client.create_playlist.assert_not_called()

    def test_unknown_provider_is_rejected_without_persistence(self):
        before = LibraryPlaylist.objects.count()

        with self.assertRaises(TransferError):
            create_library_transfer(
                playlist=self.playlist,
                target_provider="unknown",
                tracks=[self.first],
                client=Mock(),
                token="access-token",
                safe_candidate_url=self.safe_url,
            )

        self.assertEqual(LibraryPlaylist.objects.count(), before)
        self.assertFalse(LibraryTransfer.objects.exists())
