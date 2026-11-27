from unittest.mock import Mock

from django.test import TestCase

from transfer.models import (
    LibraryPlaylist,
    LibraryProfile,
    LibraryTrack,
    LibraryTransfer,
    LibraryTransferItem,
)
from transfer.services.library_transfer_review_provider import (
    apply_review_candidate_to_provider,
)


class LibraryTransferReviewProviderTests(TestCase):
    def setUp(self):
        self.profile = LibraryProfile.objects.create(session_fingerprint="r" * 64)
        self.source = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Source",
            provider=LibraryPlaylist.Provider.VK,
        )
        self.first_track = LibraryTrack.objects.create(
            playlist=self.source,
            title="First",
            artist="Artist",
            position=0,
        )
        self.second_track = LibraryTrack.objects.create(
            playlist=self.source,
            title="Second",
            artist="Artist",
            position=1,
        )
        self.review = LibraryTransfer.objects.create(
            profile=self.profile,
            source_playlist=self.source,
            target_provider=LibraryPlaylist.Provider.SOUNDCLOUD,
            total=2,
        )
        self.first_item = LibraryTransferItem.objects.create(
            transfer=self.review,
            source_track=self.first_track,
            position=0,
            status=LibraryTransferItem.Status.MATCHED,
            target_external_id="111",
        )
        self.second_item = LibraryTransferItem.objects.create(
            transfer=self.review,
            source_track=self.second_track,
            position=1,
        )
        self.provider = Mock()
        self.safe_url = lambda value, provider: (
            value if provider == "soundcloud" and value.startswith("https://") else ""
        )

    def test_creates_soundcloud_playlist_with_existing_and_selected_tracks(self):
        self.provider.create_playlist.return_value = {
            "id": 999,
            "permalink_url": "https://soundcloud.com/user/source",
        }

        playlist_id, target_url = apply_review_candidate_to_provider(
            review=self.review,
            item=self.second_item,
            candidate={"id": "222"},
            candidate_id="222",
            spotify_access=Mock(),
            soundcloud_access=lambda: (self.provider, "token"),
            safe_candidate_url=self.safe_url,
        )

        self.assertEqual(playlist_id, "999")
        self.assertEqual(target_url, "https://soundcloud.com/user/source")
        self.provider.create_playlist.assert_called_once_with(
            "token",
            "Source",
            ["111", "222"],
        )

    def test_updates_existing_soundcloud_playlist_in_source_order(self):
        self.review.provider_playlist_id = "existing-playlist"
        self.review.target_url = "https://soundcloud.com/user/source"
        self.review.save(update_fields=["provider_playlist_id", "target_url"])

        playlist_id, target_url = apply_review_candidate_to_provider(
            review=self.review,
            item=self.second_item,
            candidate={"id": "222"},
            candidate_id="222",
            spotify_access=Mock(),
            soundcloud_access=lambda: (self.provider, "token"),
            safe_candidate_url=self.safe_url,
        )

        self.assertEqual(playlist_id, "existing-playlist")
        self.assertEqual(target_url, "https://soundcloud.com/user/source")
        self.provider.update_playlist_tracks.assert_called_once_with(
            "token",
            "existing-playlist",
            ["111", "222"],
        )
        self.provider.create_playlist.assert_not_called()
