# ruff: noqa: I001
import json
from unittest import TestCase as UnitTestCase
from unittest.mock import Mock, patch
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string
from hypothesis import given, settings, strategies as st

from ..credentials import get_session_fingerprint
from ..library_views import (
    _safe_candidate_url,
    _save_soundcloud_playlist,
    _spotify_resource_id,
    _validate_soundcloud_permalink,
)
from ..models import LibraryProfile
from ..services.common import normalize_track_text, parse_vk_playlist_url, parse_vk_track_url
from ..services.library_source_search import spotify_library_search_results, soundcloud_library_search_results


FUZZ_SETTINGS = settings(max_examples=100, derandomize=True, deadline=None)


class ProviderInputFuzzTests(UnitTestCase):
    """Pure property-based tests; these cases do not need Django's database."""

    @FUZZ_SETTINGS
    @given(value=st.text(max_size=2048))
    def test_vk_url_parsers_only_return_typed_identifiers_or_validation_errors(self, value):
        for parser, expected_length in (
            (parse_vk_playlist_url, 3),
            (parse_vk_track_url, 2),
        ):
            try:
                parsed = parser(value)
            except ValueError:
                continue
            self.assertEqual(len(parsed), expected_length)
            self.assertTrue(all(isinstance(part, (int, str)) for part in parsed))
            self.assertTrue(all(isinstance(part, int) for part in parsed[:2]))

    @FUZZ_SETTINGS
    @given(
        value=st.one_of(
            st.none(),
            st.booleans(),
            st.integers(),
            st.text(max_size=1024),
            st.lists(st.text(max_size=20), max_size=5),
            st.dictionaries(st.text(max_size=20), st.text(max_size=20), max_size=5),
        )
    )
    def test_candidate_url_fuzzer_never_accepts_an_untrusted_origin(self, value):
        for provider, allowed_hosts in (
            ("spotify", {"open.spotify.com", "www.open.spotify.com"}),
            ("soundcloud", {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"}),
        ):
            result = _safe_candidate_url(value, provider)
            if not result:
                continue
            parsed = urlparse(result)
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)
            self.assertIn(parsed.port, (None, 443))
            self.assertIsNone(parsed.username)
            self.assertIsNone(parsed.password)

    @FUZZ_SETTINGS
    @given(value=st.text(max_size=2048))
    def test_track_normalization_is_idempotent_for_arbitrary_unicode(self, value):
        normalized = normalize_track_text(value)
        self.assertEqual(normalize_track_text(normalized), normalized)

    @FUZZ_SETTINGS
    @given(value=st.text(max_size=2048))
    def test_spotify_resource_url_fuzzer_only_returns_valid_playlist_ids(self, value):
        try:
            resource_id = _spotify_resource_id(value, "playlist")
        except ValueError:
            return

        parsed = urlparse(value.strip())
        self.assertEqual(parsed.scheme, "https")
        self.assertIn(parsed.hostname, {"open.spotify.com", "www.open.spotify.com"})
        self.assertIn(parsed.port, (None, 443))
        self.assertEqual(len(resource_id), 22)
        self.assertRegex(resource_id, r"^[A-Za-z0-9]{22}$")

    @FUZZ_SETTINGS
    @given(value=st.text(max_size=2048))
    def test_soundcloud_permalink_fuzzer_only_accepts_trusted_https_urls(self, value):
        try:
            accepted = _validate_soundcloud_permalink(value)
        except ValueError:
            return

        parsed = urlparse(accepted)
        self.assertEqual(parsed.scheme, "https")
        self.assertIn(parsed.hostname, {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"})
        self.assertIn(parsed.port, (None, 443))
        self.assertIsNone(parsed.username)
        self.assertIsNone(parsed.password)


class ProviderResponseFuzzTests(TestCase):
    """Fuzz provider JSON and serializer boundaries with an isolated Django test client."""

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="provider-fuzz-" + get_random_string(12),
            password=get_random_string(32),
        )
        self.client.force_login(user)
        self.profile, _ = LibraryProfile.objects.get_or_create(
            user=user,
            defaults={"session_fingerprint": get_session_fingerprint(self.client)},
        )

    def test_library_search_json_fuzzer_never_returns_server_error(self):
        @FUZZ_SETTINGS
        @given(
            title=st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=240), st.lists(st.integers(), max_size=5)),
            artist=st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=240)),
            providers=st.one_of(
                st.none(),
                st.text(max_size=40),
                st.lists(st.one_of(st.none(), st.integers(), st.text(max_size=30)), max_size=8),
            ),
        )
        def exercise(title, artist, providers):
            spotify = Mock()
            spotify.search_tracks.return_value = []
            soundcloud = Mock()
            soundcloud.search_tracks.return_value = []
            with (
                patch("transfer.library_views._spotify_access", return_value=(spotify, "test-token")),
                patch("transfer.library_views._soundcloud_access", return_value=(soundcloud, "test-token")),
            ):
                response = self.client.post(
                    reverse("library_track_search"),
                    data=json.dumps({"title": title, "artist": artist, "providers": providers}),
                    content_type="application/json",
                )
            self.assertIn(response.status_code, (200, 400))
            self.assertIsInstance(response.json(), dict)

        exercise()

    def test_malformed_spotify_search_results_are_contained_by_serializer(self):
        @FUZZ_SETTINGS
        @given(
            tracks=st.lists(
                st.one_of(
                    st.none(), st.booleans(), st.integers(), st.text(max_size=80),
                    st.dictionaries(
                        st.text(max_size=20),
                        st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=80), st.lists(st.integers(), max_size=4)),
                        max_size=8,
                    ),
                ),
                max_size=12,
            )
        )
        def exercise(tracks):
            results = spotify_library_search_results(tracks)
            self.assertIsInstance(results, list)
            self.assertTrue(all(item.get("provider") == "spotify" for item in results))

        exercise()

    def test_malformed_soundcloud_search_results_are_contained_by_serializer(self):
        @FUZZ_SETTINGS
        @given(
            tracks=st.lists(
                st.one_of(
                    st.none(), st.booleans(), st.integers(), st.text(max_size=80),
                    st.dictionaries(
                        st.text(max_size=20),
                        st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=80), st.lists(st.integers(), max_size=4)),
                        max_size=8,
                    ),
                ),
                max_size=12,
            )
        )
        def exercise(tracks):
            results = soundcloud_library_search_results(tracks)
            self.assertIsInstance(results, list)
            self.assertTrue(all(item.get("provider") == "soundcloud" for item in results))

        exercise()

    def test_soundcloud_track_serializer_survives_malformed_duration_and_artist_shapes(self):
        @FUZZ_SETTINGS
        @given(
            duration=st.one_of(
                st.none(),
                st.booleans(),
                st.integers(min_value=-10**12, max_value=10**12),
                st.text(max_size=80),
                st.floats(allow_nan=True, allow_infinity=True, width=32),
            ),
            user=st.one_of(
                st.none(),
                st.booleans(),
                st.integers(),
                st.text(max_size=40),
                st.dictionaries(st.text(max_size=20), st.text(max_size=40), max_size=3),
            ),
            artist=st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=80)),
        )
        def exercise(duration, user, artist):
            playlist, count = _save_soundcloud_playlist(
                self.profile,
                {"title": "Fuzz playlist"},
                [{"id": 123, "title": "Valid title", "duration": duration, "user": user, "metadata_artist": artist}],
                "https://soundcloud.com/artist/fuzz-playlist",
            )
            try:
                self.assertEqual(count, 1)
                track = playlist.tracks.get()
                self.assertEqual(track.title, "Valid title")
                self.assertTrue(track.artist)
                try:
                    if isinstance(duration, bool):
                        raise TypeError("Boolean duration is invalid.")
                    parsed_duration = max(0, int(duration or 0))
                    expected_duration = parsed_duration if parsed_duration <= 2_147_483_647 else None
                except (TypeError, ValueError, OverflowError):
                    expected_duration = None
                self.assertEqual(track.duration_ms, expected_duration)
            finally:
                playlist.delete()

        exercise()
