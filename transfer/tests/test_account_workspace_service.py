from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve, reverse

from transfer import auth_views
from transfer.models import (
    LibraryPlaylist,
    LibraryProfile,
    LibraryTransfer,
    OAuthCredential,
    TransferJob,
)
from transfer.services.account_workspace import attach_anonymous_workspace


class AccountWorkspaceServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="workspace-owner",
            password="a-long-test-password",
        )
        self.previous_fingerprint = "a" * 64
        self.current_fingerprint = "b" * 64

    def create_guest_profile(self):
        return LibraryProfile.objects.create(
            session_fingerprint=self.previous_fingerprint,
        )

    def test_anonymous_profile_becomes_the_account_profile(self):
        guest = self.create_guest_profile()
        playlist = LibraryPlaylist.objects.create(
            profile=guest,
            title="Guest playlist",
            provider=LibraryPlaylist.Provider.VK,
        )
        attach_anonymous_workspace(
            user=self.user,
            previous_fingerprint=self.previous_fingerprint,
            current_fingerprint=self.current_fingerprint,
        )

        guest.refresh_from_db()
        self.assertEqual(guest.user, self.user)
        self.assertEqual(guest.session_fingerprint, self.current_fingerprint)
        self.assertEqual(guest.playlists.get(), playlist)

    def test_guest_library_is_merged_into_existing_account_profile(self):
        guest = self.create_guest_profile()
        account = LibraryProfile.objects.create(
            user=self.user,
            session_fingerprint="c" * 64,
        )
        playlist = LibraryPlaylist.objects.create(
            profile=guest,
            title="Guest playlist",
            provider=LibraryPlaylist.Provider.VK,
        )
        target_playlist = LibraryPlaylist.objects.create(
            profile=account,
            title="Existing playlist",
            provider=LibraryPlaylist.Provider.MANUAL,
        )
        transfer = LibraryTransfer.objects.create(
            profile=guest,
            source_playlist=playlist,
            target_provider=LibraryPlaylist.Provider.SPOTIFY,
            provider_playlist_id="",
        )

        attach_anonymous_workspace(
            user=self.user,
            previous_fingerprint=self.previous_fingerprint,
            current_fingerprint=self.current_fingerprint,
        )

        self.assertFalse(LibraryProfile.objects.filter(pk=guest.pk).exists())
        playlist.refresh_from_db()
        transfer.refresh_from_db()
        self.assertEqual(playlist.profile, account)
        self.assertEqual(transfer.profile, account)
        self.assertEqual(
            set(account.playlists.values_list("pk", flat=True)),
            {playlist.pk, target_playlist.pk},
        )

    def test_credentials_move_and_duplicate_provider_credential_is_discarded(self):
        old_spotify = OAuthCredential.objects.create(
            session_fingerprint=self.previous_fingerprint,
            provider=OAuthCredential.Provider.SPOTIFY,
            encrypted_payload="old-spotify",
        )
        existing_spotify = OAuthCredential.objects.create(
            session_fingerprint=self.current_fingerprint,
            provider=OAuthCredential.Provider.SPOTIFY,
            encrypted_payload="current-spotify",
        )
        old_soundcloud = OAuthCredential.objects.create(
            session_fingerprint=self.previous_fingerprint,
            provider=OAuthCredential.Provider.SOUNDCLOUD,
            encrypted_payload="soundcloud",
        )

        attach_anonymous_workspace(
            user=self.user,
            previous_fingerprint=self.previous_fingerprint,
            current_fingerprint=self.current_fingerprint,
        )

        self.assertFalse(OAuthCredential.objects.filter(pk=old_spotify.pk).exists())
        self.assertEqual(
            OAuthCredential.objects.get(pk=existing_spotify.pk).encrypted_payload,
            "current-spotify",
        )
        old_soundcloud.refresh_from_db()
        self.assertEqual(old_soundcloud.session_fingerprint, self.current_fingerprint)

    def test_finished_jobs_move_but_second_active_job_stays_with_guest_session(self):
        current_active = TransferJob.objects.create(
            session_fingerprint=self.current_fingerprint,
            source_url="https://vk.ru/music/playlist/1_2",
            status=TransferJob.Status.QUEUED,
        )
        finished = TransferJob.objects.create(
            session_fingerprint=self.previous_fingerprint,
            source_url="https://vk.ru/music/playlist/1_3",
            status=TransferJob.Status.SUCCEEDED,
        )
        old_active = TransferJob.objects.create(
            session_fingerprint=self.previous_fingerprint,
            source_url="https://vk.ru/music/playlist/1_4",
            status=TransferJob.Status.RUNNING,
        )

        attach_anonymous_workspace(
            user=self.user,
            previous_fingerprint=self.previous_fingerprint,
            current_fingerprint=self.current_fingerprint,
        )

        finished.refresh_from_db()
        old_active.refresh_from_db()
        current_active.refresh_from_db()
        self.assertEqual(finished.session_fingerprint, self.current_fingerprint)
        self.assertEqual(old_active.session_fingerprint, self.previous_fingerprint)
        self.assertEqual(current_active.status, TransferJob.Status.QUEUED)

    def test_all_jobs_move_when_account_has_no_active_job(self):
        queued = TransferJob.objects.create(
            session_fingerprint=self.previous_fingerprint,
            source_url="https://vk.ru/music/playlist/1_2",
            status=TransferJob.Status.QUEUED,
        )
        attach_anonymous_workspace(
            user=self.user,
            previous_fingerprint=self.previous_fingerprint,
            current_fingerprint=self.current_fingerprint,
        )
        queued.refresh_from_db()
        self.assertEqual(queued.session_fingerprint, self.current_fingerprint)

    def test_same_fingerprint_is_a_no_op(self):
        guest = self.create_guest_profile()
        attach_anonymous_workspace(
            user=self.user,
            previous_fingerprint=self.previous_fingerprint,
            current_fingerprint=self.previous_fingerprint,
        )
        guest.refresh_from_db()
        self.assertIsNone(guest.user_id)

    def test_authentication_urls_remain_bound_to_auth_view_handlers(self):
        expected = {
            "register": "register",
            "login": "sign_in",
            "logout": "sign_out",
        }
        for route_name, function_name in expected.items():
            with self.subTest(route_name=route_name):
                self.assertIs(resolve(reverse(route_name)).func, getattr(auth_views, function_name))

    def test_auth_views_use_the_extracted_workspace_service(self):
        self.assertIs(auth_views.attach_anonymous_workspace, attach_anonymous_workspace)
