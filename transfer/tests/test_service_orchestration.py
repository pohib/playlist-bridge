from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from ..services import TransferError
from ..services.transfer_service import execute_transfer


class ExecuteTransferTests(SimpleTestCase):
    def setUp(self):
        self.track = SimpleNamespace(
            artist="Artist",
            title="Track",
            duration=180,
        )
        self.candidate = {
            "name": "Track",
            "artists": [{"name": "Artist"}],
            "duration_ms": 180000,
            "uri": "spotify:track:" + "A" * 22,
        }

    @patch("transfer.services.transfer_service.VKClient")
    def test_successful_transfer_creates_private_playlist_and_reports_progress(self, vk_class):
        vk_class.return_value.fetch_playlist.return_value = ("Source playlist", [self.track])
        spotify = Mock()
        spotify.current_user.return_value = {"id": "spotify-user"}
        spotify.search.return_value = [self.candidate]
        spotify.create_playlist.return_value = "B" * 22
        spotify.get_playlist_items.return_value = []
        progress = []
        token_provider = Mock(side_effect=["token-1", "token-2", "token-3", "token-4"])

        result = execute_transfer(
            vk_version="5.289",
            spotify=spotify,
            spotify_token="initial-token",
            source_url="https://vk.ru/music/playlist/10_5_key",
            progress_callback=progress.append,
            token_provider=token_provider,
        )

        self.assertEqual(result["playlist_name"], "Source playlist")
        self.assertEqual(result["target_playlist_id"], "B" * 22)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["not_found"], 0)
        self.assertEqual(result["ambiguous"], 0)
        self.assertEqual(result["report"][0]["status"], "matched")
        spotify.create_playlist.assert_called_once_with("token-3", "Source playlist")
        spotify.get_playlist_items.assert_called()
        spotify.add_items.assert_called_once_with("token-4", "B" * 22, [self.candidate["uri"]])
        self.assertEqual(progress[0]["progress"], 90)
        self.assertEqual(progress[0]["matched"], 1)
        self.assertEqual(token_provider.call_count, 4)

    @patch("transfer.services.transfer_service.VKClient")
    def test_existing_target_playlist_is_validated_before_search(self, vk_class):
        vk_class.return_value.fetch_playlist.return_value = ("Source playlist", [self.track])
        spotify = Mock()
        spotify.current_user.return_value = {"id": "spotify-user"}

        with self.assertRaisesRegex(TransferError, "корректную ссылку"):
            execute_transfer(
                vk_version="5.289",
                spotify=spotify,
                spotify_token="token",
                source_url="https://vk.ru/music/playlist/10_5_key",
                target_playlist="https://attacker.example/playlist/" + "A" * 22,
            )

        spotify.verify_playlist_access.assert_not_called()
        spotify.search.assert_not_called()

    @patch("transfer.services.transfer_service.VKClient")
    def test_existing_playlist_must_belong_to_connected_user(self, vk_class):
        vk_class.return_value.fetch_playlist.return_value = ("Source playlist", [self.track])
        spotify = Mock()
        spotify.current_user.return_value = {"id": "spotify-user"}
        spotify.verify_playlist_access.side_effect = TransferError("not owner")

        with self.assertRaisesRegex(TransferError, "not owner"):
            execute_transfer(
                vk_version="5.289",
                spotify=spotify,
                spotify_token="token",
                source_url="https://vk.ru/music/playlist/10_5_key",
                target_playlist="A" * 22,
            )

        spotify.verify_playlist_access.assert_called_once_with("token", "A" * 22, "spotify-user")
        spotify.search.assert_not_called()

    @patch("transfer.services.transfer_service.VKClient")
    def test_no_match_does_not_create_empty_spotify_playlist(self, vk_class):
        vk_class.return_value.fetch_playlist.return_value = ("Source playlist", [self.track])
        spotify = Mock()
        spotify.current_user.return_value = {"id": "spotify-user"}
        spotify.search.return_value = []

        with self.assertRaisesRegex(TransferError, "ни одной композиции"):
            execute_transfer(
                vk_version="5.289",
                spotify=spotify,
                spotify_token="token",
                source_url="https://vk.ru/music/playlist/10_5_key",
            )

        spotify.create_playlist.assert_not_called()
        spotify.add_items.assert_not_called()


    @patch("transfer.services.transfer_service.VKClient")
    def test_resume_uses_saved_match_checkpoint_and_reconciles_already_added_tracks(self, vk_class):
        vk_class.return_value.fetch_playlist.return_value = ("Source playlist", [self.track])
        spotify = Mock()
        spotify.current_user.return_value = {"id": "spotify-user"}
        spotify.verify_playlist_access.return_value = {}
        spotify.get_playlist_items.return_value = [
            {"track": {"uri": self.candidate["uri"]}}
        ]
        saved = []
        checkpoint = {
            "version": 1,
            "source_track_count": 1,
            "playlist_name": "Source playlist",
            "report": [{
                "index": 1, "artist": "Artist", "title": "Track",
                "status": "matched", "spotify_name": "Track", "score": 1.0,
            }],
            "matched_uris": [self.candidate["uri"]],
            "target_playlist_id": "B" * 22,
            "baseline_counts": {},
        }

        result = execute_transfer(
            vk_version="5.289",
            spotify=spotify,
            spotify_token="token",
            source_url="https://vk.ru/music/playlist/10_5_key",
            checkpoint=checkpoint,
            checkpoint_callback=saved.append,
        )

        self.assertEqual(result["target_playlist_id"], "B" * 22)
        spotify.search.assert_not_called()
        spotify.create_playlist.assert_not_called()
        spotify.add_items.assert_not_called()
        self.assertTrue(saved[-1]["completed"])

    @patch("transfer.services.transfer_service.VKClient")
    def test_resume_adds_only_missing_duplicate_occurrences(self, vk_class):
        vk_class.return_value.fetch_playlist.return_value = ("Source playlist", [self.track, self.track])
        uri = self.candidate["uri"]
        spotify = Mock()
        spotify.current_user.return_value = {"id": "spotify-user"}
        spotify.verify_playlist_access.return_value = {}
        spotify.get_playlist_items.return_value = [{"track": {"uri": uri}}]
        checkpoint = {
            "version": 1,
            "source_track_count": 2,
            "playlist_name": "Source playlist",
            "report": [
                {"index": 1, "artist": "Artist", "title": "Track", "status": "matched", "spotify_name": "Track", "score": 1.0},
                {"index": 2, "artist": "Artist", "title": "Track", "status": "matched", "spotify_name": "Track", "score": 1.0},
            ],
            "matched_uris": [uri, uri],
            "target_playlist_id": "B" * 22,
            "baseline_counts": {},
        }

        execute_transfer(
            vk_version="5.289",
            spotify=spotify,
            spotify_token="token",
            source_url="https://vk.ru/music/playlist/10_5_key",
            checkpoint=checkpoint,
        )

        spotify.add_items.assert_called_once_with("token", "B" * 22, [uri])

    @patch("transfer.services.transfer_service.VKClient")
    def test_ambiguous_match_is_not_added_automatically(self, vk_class):
        vk_class.return_value.fetch_playlist.return_value = ("Source playlist", [self.track])
        spotify = Mock()
        spotify.current_user.return_value = {"id": "spotify-user"}
        spotify.search.return_value = [self.candidate, dict(self.candidate)]

        with self.assertRaisesRegex(TransferError, "ни одной композиции"):
            execute_transfer(
                vk_version="5.289",
                spotify=spotify,
                spotify_token="token",
                source_url="https://vk.ru/music/playlist/10_5_key",
            )

        spotify.create_playlist.assert_not_called()
        spotify.add_items.assert_not_called()
