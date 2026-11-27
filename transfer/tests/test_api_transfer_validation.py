from django.test import SimpleTestCase

from transfer.services.api_transfer_validation import (
    TransferRequestValidationError,
    validate_transfer_request_payload,
)


class TransferRequestValidationTests(SimpleTestCase):
    def test_accepts_vk_playlist_and_normalizes_spotify_playlist_id(self):
        source_url = "https://vk.com/music/playlist/241688629_40"
        target_id = "A" * 22

        self.assertEqual(
            validate_transfer_request_payload(
                {
                    "source_url": source_url,
                    "target_playlist": f"  {target_id}  ",
                }
            ),
            (source_url, target_id),
        )

    def test_accepts_missing_or_null_target_playlist(self):
        source_url = "https://vk.ru/music/playlist/-1_2"

        self.assertEqual(
            validate_transfer_request_payload({"source_url": source_url}),
            (source_url, ""),
        )
        self.assertEqual(
            validate_transfer_request_payload(
                {"source_url": source_url, "target_playlist": None}
            ),
            (source_url, ""),
        )

    def test_rejects_non_object_payload(self):
        with self.assertRaises(TransferRequestValidationError) as error:
            validate_transfer_request_payload([])

        self.assertEqual(str(error.exception), "Ожидается JSON-объект.")

    def test_rejects_invalid_source_url_type_or_length(self):
        for source_url in (None, 123, "x" * 2049):
            with self.subTest(source_url=type(source_url).__name__):
                with self.assertRaises(TransferRequestValidationError) as error:
                    validate_transfer_request_payload({"source_url": source_url})

                self.assertIn("source_url", str(error.exception))

    def test_rejects_non_string_or_oversized_target_playlist(self):
        for target in (123, [], "x" * 2049):
            with self.subTest(target=type(target).__name__):
                with self.assertRaises(TransferRequestValidationError) as error:
                    validate_transfer_request_payload(
                        {
                            "source_url": "https://vk.com/music/playlist/1_2",
                            "target_playlist": target,
                        }
                    )

                self.assertIn("target_playlist", str(error.exception))

    def test_rejects_invalid_spotify_playlist_id(self):
        with self.assertRaises(TransferRequestValidationError) as error:
            validate_transfer_request_payload(
                {
                    "source_url": "https://vk.com/music/playlist/1_2",
                    "target_playlist": "not-a-spotify-id",
                }
            )

        self.assertIn("Spotify ID", str(error.exception))

    def test_rejects_non_vk_or_malformed_playlist_urls(self):
        for source_url in (
            "https://example.com/music/playlist/1_2",
            "ftp://vk.com/music/playlist/1_2",
            "https://vk.com/audio1_2",
        ):
            with self.subTest(source_url=source_url):
                with self.assertRaises(TransferRequestValidationError) as error:
                    validate_transfer_request_payload({"source_url": source_url})

                self.assertEqual(
                    str(error.exception),
                    "Укажи корректную ссылку на плейлист VK.",
                )
