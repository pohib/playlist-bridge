from unittest.mock import Mock, patch

from django.test import TestCase

from transfer.models import LibraryProfile, OAuthCredential, TransferJob
from transfer.services.oauth_session_service import connected_providers, rotate_session_binding


class OAuthSessionServiceTests(TestCase):
    def setUp(self):
        self.old_fingerprint = "o" * 64
        self.new_fingerprint = "n" * 64
        self.request = Mock()
        self.request.session = Mock()

    @patch("transfer.services.oauth_session_service.get_session_fingerprint")
    def test_rotate_session_binding_moves_all_session_owned_records_atomically(
        self, fingerprint
    ):
        fingerprint.side_effect = [self.old_fingerprint, self.new_fingerprint]
        credential = OAuthCredential.objects.create(
            session_fingerprint=self.old_fingerprint,
            provider=OAuthCredential.Provider.SPOTIFY,
            encrypted_payload="encrypted",
        )
        job = TransferJob.objects.create(
            session_fingerprint=self.old_fingerprint,
            source_url="https://vk.ru/music/playlist/1_2",
        )
        profile = LibraryProfile.objects.create(
            session_fingerprint=self.old_fingerprint
        )

        result = rotate_session_binding(self.request)

        self.assertEqual(result, self.new_fingerprint)
        self.request.session.cycle_key.assert_called_once_with()
        credential.refresh_from_db()
        job.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(credential.session_fingerprint, self.new_fingerprint)
        self.assertEqual(job.session_fingerprint, self.new_fingerprint)
        self.assertEqual(profile.session_fingerprint, self.new_fingerprint)

    @patch("transfer.services.oauth_session_service.get_session_fingerprint")
    def test_connected_providers_returns_spotify_and_soundcloud_flags(
        self, fingerprint
    ):
        fingerprint.return_value = self.old_fingerprint
        OAuthCredential.objects.create(
            session_fingerprint=self.old_fingerprint,
            provider=OAuthCredential.Provider.SPOTIFY,
            encrypted_payload="encrypted",
        )
        OAuthCredential.objects.create(
            session_fingerprint=self.old_fingerprint,
            provider=OAuthCredential.Provider.SOUNDCLOUD,
            encrypted_payload="encrypted",
        )
        OAuthCredential.objects.create(
            session_fingerprint="x" * 64,
            provider=OAuthCredential.Provider.VK,
            encrypted_payload="encrypted",
        )

        self.assertEqual(connected_providers(self.request), (True, False, True))

    @patch("transfer.services.oauth_session_service.get_session_fingerprint")
    def test_connected_providers_does_not_leak_other_sessions(self, fingerprint):
        fingerprint.return_value = self.old_fingerprint
        OAuthCredential.objects.create(
            session_fingerprint="x" * 64,
            provider=OAuthCredential.Provider.SPOTIFY,
            encrypted_payload="encrypted",
        )

        self.assertEqual(connected_providers(self.request), (False, False, False))
