from io import BytesIO

from django.test import SimpleTestCase

from transfer.services.audio_file_validation import (
    SOUNDCLOUD_AUDIO_EXTENSIONS,
    has_audio_file_signature,
)


class AudioFileValidationTests(SimpleTestCase):
    def test_all_supported_extensions_have_signature_checks(self):
        self.assertEqual(
            SOUNDCLOUD_AUDIO_EXTENSIONS,
            {
                ".mp3", ".wav", ".flac", ".aiff", ".aif",
                ".ogg", ".aac", ".amr", ".wma", ".mp2",
            },
        )

    def test_accepts_valid_headers_for_supported_formats(self):
        headers = {
            ".wav": b"RIFF" + b"\x00" * 4 + b"WAVE" + b"data",
            ".flac": b"fLaC" + b"\x00" * 12,
            ".aiff": b"FORM" + b"\x00" * 4 + b"AIFF" + b"data",
            ".aif": b"FORM" + b"\x00" * 4 + b"AIFC" + b"data",
            ".ogg": b"OggS" + b"\x00" * 12,
            ".amr": b"#!AMR" + b"\x00" * 11,
            ".wma": bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c"),
            ".aac": b"\xff\xf1" + b"\x00" * 14,
            ".mp3": b"ID3" + b"\x00" * 13,
            ".mp2": b"\xff\xe0" + b"\x00" * 14,
        }

        for extension, header in headers.items():
            with self.subTest(extension=extension):
                uploaded = BytesIO(header)
                self.assertTrue(has_audio_file_signature(uploaded, extension))
                self.assertEqual(uploaded.tell(), 0)

    def test_rejects_mismatched_and_unsupported_formats(self):
        uploaded = BytesIO(b"<html>not audio</html>")

        for extension in SOUNDCLOUD_AUDIO_EXTENSIONS | {".exe"}:
            with self.subTest(extension=extension):
                self.assertFalse(has_audio_file_signature(uploaded, extension))
                uploaded.seek(0)

    def test_rejects_unreadable_upload_objects(self):
        class Unreadable:
            def read(self, size):
                raise OSError("read failed")

        self.assertFalse(has_audio_file_signature(Unreadable(), ".mp3"))
