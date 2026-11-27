from unittest.mock import Mock, patch

from django.test import TestCase

from transfer.models import LibraryPlaylist, LibraryProfile, LibraryTrack
from transfer.services import TransferError
from transfer.services.library_transfer_workflow import create_library_transfer_workflow


class LibraryTransferWorkflowTests(TestCase):
    def setUp(self):
        self.profile = LibraryProfile.objects.create(session_fingerprint="w" * 64)
        self.playlist = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Workflow playlist",
            provider=LibraryPlaylist.Provider.VK,
        )
        self.track = LibraryTrack.objects.create(
            playlist=self.playlist,
            title="Track",
            artist="Artist",
            position=0,
        )
        self.safe_url = Mock(side_effect=lambda value, provider: value or "")

    @patch("transfer.services.library_transfer_workflow.create_library_transfer")
    @patch("transfer.services.library_transfer_workflow.get_access_token")
    @patch("transfer.services.library_transfer_workflow.SpotifyClient")
    def test_spotify_workflow_builds_client_authorizes_and_delegates(
        self, client_factory, get_token, create_transfer
    ):
        client = client_factory.return_value
        get_token.return_value = ("access-token", {"access_token": "access-token"})
        expected = (Mock(), {self.track.pk: {"id": "remote"}}, [])
        create_transfer.return_value = expected

        result = create_library_transfer_workflow(
            playlist=self.playlist,
            target_provider=LibraryPlaylist.Provider.SPOTIFY,
            fingerprint="fingerprint",
            safe_candidate_url=self.safe_url,
        )

        self.assertEqual(result, expected)
        client_factory.assert_called_once()
        get_token.assert_called_once_with("fingerprint", "spotify", client)
        create_transfer.assert_called_once_with(
            playlist=self.playlist,
            target_provider="spotify",
            tracks=[self.track],
            client=client,
            token="access-token",
            safe_candidate_url=self.safe_url,
        )

    @patch("transfer.services.library_transfer_workflow.create_library_transfer")
    @patch("transfer.services.library_transfer_workflow.get_access_token")
    @patch("transfer.services.library_transfer_workflow.SoundCloudClient")
    def test_soundcloud_workflow_uses_soundcloud_credentials(
        self, client_factory, get_token, create_transfer
    ):
        client = client_factory.return_value
        get_token.return_value = ("soundcloud-token", {})
        expected = (Mock(), {}, [])
        create_transfer.return_value = expected

        result = create_library_transfer_workflow(
            playlist=self.playlist,
            target_provider=LibraryPlaylist.Provider.SOUNDCLOUD,
            fingerprint="fingerprint",
            safe_candidate_url=self.safe_url,
        )

        self.assertEqual(result, expected)
        client_factory.assert_called_once()
        get_token.assert_called_once_with("fingerprint", "soundcloud", client)

    def test_invalid_provider_is_rejected_before_authorization(self):
        with patch("transfer.services.library_transfer_workflow.get_access_token") as get_token:
            with self.assertRaisesMessage(TransferError, "Выбери поддерживаемый целевой сервис."):
                create_library_transfer_workflow(
                    playlist=self.playlist,
                    target_provider="invalid",
                    fingerprint="fingerprint",
                    safe_candidate_url=self.safe_url,
                )
        get_token.assert_not_called()

    def test_empty_playlist_is_rejected(self):
        self.playlist.tracks.all().delete()

        with self.assertRaisesMessage(TransferError, "В плейлисте нет композиций для переноса."):
            create_library_transfer_workflow(
                playlist=self.playlist,
                target_provider=LibraryPlaylist.Provider.SPOTIFY,
                fingerprint="fingerprint",
                safe_candidate_url=self.safe_url,
            )

    def test_playlist_over_limit_is_rejected_before_authorization(self):
        LibraryTrack.objects.bulk_create([
            LibraryTrack(
                playlist=self.playlist,
                title=f"Track {index}",
                artist="Artist",
                position=index + 1,
            )
            for index in range(100)
        ])

        with patch("transfer.services.library_transfer_workflow.get_access_token") as get_token:
            with self.assertRaisesMessage(
                TransferError,
                "Пока можно переносить не более 100 композиций за один запуск.",
            ):
                create_library_transfer_workflow(
                    playlist=self.playlist,
                    target_provider=LibraryPlaylist.Provider.SPOTIFY,
                    fingerprint="fingerprint",
                    safe_candidate_url=self.safe_url,
                )
        get_token.assert_not_called()
