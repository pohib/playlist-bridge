from unittest.mock import Mock

import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from ..services import ReauthorizationRequired, TransferError
from ..services.soundcloud_client import SoundCloudClient
from ..services.spotify_client import SpotifyClient
from ..services.vk_audio_metadata import cover_from_item, track_from_item
from ..services.vk_client import VKClient


class SpotifyClientBehaviorTests(SimpleTestCase):
    def setUp(self):
        self.client = SpotifyClient("client-id", "client-secret", "https://example.test/callback/")

    def test_token_request_maps_invalid_grant_to_reauthorization(self):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("invalid grant")
        response.json.return_value = {"error": "invalid_grant"}
        self.client.http.post = Mock(return_value=response)

        with self.assertRaises(ReauthorizationRequired):
            self.client.token_request({"grant_type": "refresh_token", "refresh_token": "expired"})

    def test_playlist_creation_requires_provider_id(self):
        self.client.api = Mock(return_value={"name": "Created without ID"})

        with self.assertRaisesRegex(TransferError, "не вернул ID"):
            self.client.create_playlist("token", "Playlist")

    def test_playlist_access_is_limited_to_connected_account_owner(self):
        self.client.api = Mock(return_value={"owner": {"id": "another-user"}})

        with self.assertRaisesRegex(TransferError, "только в плейлист владельца"):
            self.client.verify_playlist_access("token", "A" * 22, "connected-user")

    def test_playlist_listing_follows_pages_until_provider_reports_end(self):
        self.client.api = Mock(side_effect=[
            {"items": [{"id": "one"}], "next": "next-page", "total": 2},
            {"items": [{"id": "two"}], "next": None, "total": 2},
        ])

        result = self.client.my_playlists("token")

        self.assertEqual([item["id"] for item in result], ["one", "two"])
        self.assertEqual(self.client.api.call_count, 2)
        self.assertEqual(self.client.api.call_args_list[0].kwargs["params"], {"limit": 50, "offset": 0})
        self.assertEqual(self.client.api.call_args_list[1].kwargs["params"], {"limit": 50, "offset": 50})

    def test_playlist_track_listing_follows_pages(self):
        self.client.api = Mock(side_effect=[
            {"items": [{"id": "one"}], "next": "next-page"},
            {"items": [{"id": "two"}], "next": None},
        ])

        result = self.client.get_playlist_items("token", "A" * 22)

        self.assertEqual([item["id"] for item in result], ["one", "two"])
        self.assertEqual(self.client.api.call_count, 2)

    def test_add_items_rejects_untrusted_uri_before_api_call(self):
        self.client.api = Mock()

        with self.assertRaisesRegex(TransferError, "некорректный Spotify track URI"):
            self.client.add_items("token", "A" * 22, ["https://attacker.example/track"])

        self.client.api.assert_not_called()

    def test_add_items_splits_large_batches_and_preserves_position(self):
        uris = ["spotify:track:" + "A" * 22 for _ in range(101)]
        self.client.api = Mock()

        self.client.add_items("token", "A" * 22, uris, position=4)

        self.assertEqual(self.client.api.call_count, 2)
        first_body = self.client.api.call_args_list[0].kwargs["body"]
        second_body = self.client.api.call_args_list[1].kwargs["body"]
        self.assertEqual(len(first_body["uris"]), 100)
        self.assertEqual(first_body["position"], 4)
        self.assertEqual(len(second_body["uris"]), 1)
        self.assertEqual(second_body["position"], 104)

    def test_track_details_rejects_invalid_id_without_http_request(self):
        self.client.http.get = Mock()

        with self.assertRaisesRegex(TransferError, "ID трека"):
            self.client.track_details("token", "../admin")

        self.client.http.get.assert_not_called()


class SoundCloudClientBehaviorTests(SimpleTestCase):
    def setUp(self):
        self.client = SoundCloudClient("client-id", "client-secret", "https://example.test/callback/")

    def test_token_request_maps_invalid_grant_to_reauthorization(self):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("invalid grant")
        response.json.return_value = {"error": "invalid_grant"}
        self.client.http.post = Mock(return_value=response)

        with self.assertRaises(ReauthorizationRequired):
            self.client.token_request({"grant_type": "refresh_token", "refresh_token": "expired"})

    def test_api_redirect_is_rejected(self):
        response = Mock(status_code=302, content=b"")
        self.client.http.request = Mock(return_value=response)

        with self.assertRaisesRegex(TransferError, "redirect"):
            self.client.current_user("token")

    def test_untrusted_next_page_url_is_rejected_before_request(self):
        response = Mock(status_code=200, content=b'{"collection":[],"next_href":"https://attacker.example/steal"}')
        response.json.return_value = {
            "collection": [{"id": 1}],
            "next_href": "https://attacker.example/steal",
        }
        self.client.http.request = Mock(return_value=response)

        with self.assertRaisesRegex(TransferError, "недопустимый адрес"):
            self.client.my_playlists("token")

        self.client.http.request.assert_called_once()

    def test_collection_follows_trusted_next_page(self):
        self.client._request = Mock(side_effect=[
            {
                "collection": [{"id": 1}],
                "next_href": "https://api.soundcloud.com/me/playlists?cursor=next",
            },
            {"collection": [{"id": 2}], "next_href": None},
        ])

        result = self.client.my_playlists("token")

        self.assertEqual([item["id"] for item in result], [1, 2])
        self.assertEqual(self.client._request.call_args_list[1].args[1], "https://api.soundcloud.com/me/playlists?cursor=next")
        self.assertIsNone(self.client._request.call_args_list[1].kwargs["params"])

    def test_playlist_tracks_rejects_non_numeric_id_without_request(self):
        self.client._collection = Mock()

        with self.assertRaisesRegex(TransferError, "идентификатор плейлиста"):
            self.client.playlist_tracks("token", "../admin")

        self.client._collection.assert_not_called()

    def test_create_playlist_enforces_track_ids_and_private_visibility(self):
        self.client._request = Mock(return_value={"id": 123})

        with self.assertRaisesRegex(TransferError, "некорректные ID"):
            self.client.create_playlist("token", "Playlist", ["../admin"])

        self.client._request.assert_not_called()
        self.client.create_playlist("token", "Playlist", ["123", "456"], "Description")
        payload = self.client._request.call_args.kwargs["json_body"]["playlist"]
        self.assertEqual(payload["sharing"], "private")
        self.assertEqual(payload["tracks"], [{"id": 123}, {"id": 456}])

    def test_upload_track_requires_provider_confirmation(self):
        response = Mock()
        response.status_code = 201
        response.raise_for_status.return_value = None
        response.json.return_value = {"title": "Uploaded without ID"}
        self.client.http.post = Mock(return_value=response)
        upload = SimpleUploadedFile("track.mp3", b"ID3" + b"\x00" * 20, content_type="audio/mpeg")

        with self.assertRaisesRegex(TransferError, "не подтвердил загрузку"):
            self.client.upload_track("token", upload, "Title", "Artist")

    def test_upload_track_sends_private_asset(self):
        response = Mock()
        response.status_code = 201
        response.raise_for_status.return_value = None
        response.json.return_value = {"id": 321}
        self.client.http.post = Mock(return_value=response)
        upload = SimpleUploadedFile("track.mp3", b"ID3" + b"\x00" * 20, content_type="audio/mpeg")

        result = self.client.upload_track("token", upload, "Title", "Artist")

        self.assertEqual(result["id"], 321)
        kwargs = self.client.http.post.call_args.kwargs
        self.assertEqual(kwargs["data"]["track[sharing]"], "private")
        self.assertEqual(kwargs["files"]["track[asset_data]"][0], "track.mp3")
        self.assertIs(kwargs["allow_redirects"], False)



class VKAudioMetadataTests(SimpleTestCase):
    def test_cover_extraction_accepts_only_trusted_https_hosts(self):
        self.assertEqual(
            cover_from_item({"album": {"thumb": {"photo_600": "https://cdn.userapi.com/cover.jpg"}}}),
            "https://cdn.userapi.com/cover.jpg",
        )
        self.assertEqual(
            cover_from_item({"cover_url": "https://attacker.example/cover.jpg"}),
            "",
        )
        self.assertEqual(
            cover_from_item({"cover_url": "http://cdn.userapi.com/cover.jpg"}),
            "",
        )

    def test_cover_extraction_supports_protocol_relative_vk_artwork(self):
        self.assertEqual(
            cover_from_item({"photo_300": "//sun9.userapi.com/cover.jpg"}),
            "https://sun9.userapi.com/cover.jpg",
        )

    def test_track_normalization_returns_none_for_malformed_provider_payload(self):
        self.assertIsNone(track_from_item({"owner_id": "bad", "id": 12}))
        self.assertIsNone(track_from_item(None))

    def test_track_normalization_preserves_access_key_audio_reference(self):
        track = track_from_item(
            {
                "owner_id": 241688629,
                "id": 456241110,
                "artist": "Artist",
                "title": "Title",
                "duration": 180,
                "photo_600": "https://sun9.userapi.com/cover.jpg",
            },
            "241688629_456241110_secretKey",
        )
        self.assertIsNotNone(track)
        self.assertEqual(track.audio_id, "241688629_456241110_secretKey")
        self.assertEqual(track.cover_url, "https://sun9.userapi.com/cover.jpg")

    def test_vk_client_legacy_metadata_helpers_delegate_to_pure_functions(self):
        item = {
            "owner_id": 1,
            "id": 2,
            "artist": "Artist",
            "title": "Title",
            "duration": 10,
            "photo_300": "https://sun9.userapi.com/cover.jpg",
        }
        self.assertEqual(VKClient._cover_from_item(item), cover_from_item(item))
        self.assertEqual(VKClient._track_from_item(item), track_from_item(item))
