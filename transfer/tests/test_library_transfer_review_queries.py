from django.http import Http404
from django.test import TestCase

from transfer.models import (
    LibraryPlaylist,
    LibraryProfile,
    LibraryTrack,
    LibraryTransfer,
    LibraryTransferItem,
)
from transfer.services.library_transfer_review_queries import (
    get_transfer_candidate_url,
    get_transfer_review_page,
    get_transfer_target_url,
)


class LibraryTransferReviewQueryTests(TestCase):
    def setUp(self):
        self.profile = LibraryProfile.objects.create(session_fingerprint="q" * 64)
        self.other_profile = LibraryProfile.objects.create(session_fingerprint="r" * 64)
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
            target_url="https://open.spotify.com/playlist/" + "A" * 22,
            total=1,
        )
        self.item = LibraryTransferItem.objects.create(
            transfer=self.review,
            source_track=self.track,
            position=0,
            candidates=[{
                "id": "B" * 22,
                "url": "https://open.spotify.com/track/" + "B" * 22,
            }],
        )
        self.safe_url = lambda value, provider: (
            value
            if isinstance(value, str) and value.startswith("https://open.spotify.com/")
            else ""
        )

    def test_review_page_returns_first_pending_item_and_items(self):
        review, items, first_pending_id = get_transfer_review_page(
            profile=self.profile,
            transfer_id=self.review.pk,
        )

        self.assertEqual(review.pk, self.review.pk)
        self.assertEqual(list(items), [self.item])
        self.assertEqual(first_pending_id, self.item.pk)

    def test_review_page_hides_another_profiles_transfer(self):
        with self.assertRaises(Http404):
            get_transfer_review_page(
                profile=self.other_profile,
                transfer_id=self.review.pk,
            )

    def test_target_url_is_validated_and_owner_scoped(self):
        review, target_url = get_transfer_target_url(
            profile=self.profile,
            transfer_id=self.review.pk,
            safe_candidate_url=self.safe_url,
        )
        self.assertEqual(review.pk, self.review.pk)
        self.assertEqual(target_url, self.review.target_url)

        with self.assertRaises(Http404):
            get_transfer_target_url(
                profile=self.other_profile,
                transfer_id=self.review.pk,
                safe_candidate_url=self.safe_url,
            )

    def test_candidate_url_requires_a_stored_candidate_and_owner(self):
        review, candidate_url = get_transfer_candidate_url(
            profile=self.profile,
            transfer_id=self.review.pk,
            item_id=self.item.pk,
            candidate_id="B" * 22,
            safe_candidate_url=self.safe_url,
        )
        self.assertEqual(review.pk, self.review.pk)
        self.assertEqual(candidate_url, self.item.candidates[0]["url"])

        _, unknown_candidate_url = get_transfer_candidate_url(
            profile=self.profile,
            transfer_id=self.review.pk,
            item_id=self.item.pk,
            candidate_id="unknown",
            safe_candidate_url=self.safe_url,
        )
        self.assertEqual(unknown_candidate_url, "")

        with self.assertRaises(Http404):
            get_transfer_candidate_url(
                profile=self.other_profile,
                transfer_id=self.review.pk,
                item_id=self.item.pk,
                candidate_id="B" * 22,
                safe_candidate_url=self.safe_url,
            )
