import json
from unittest.mock import Mock, patch
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string
from hypothesis import given, settings
from hypothesis import strategies as st

from .credentials import get_session_fingerprint
from .library_views import _safe_candidate_url
from .models import LibraryProfile
from .services.common import normalize_track_text, parse_vk_playlist_url, parse_vk_track_url


FUZZ_SETTINGS = settings(max_examples=100, derandomize=True, deadline=None)


class ProviderInputFuzzTests(TestCase):
    """Property-based tests for untrusted URLs and provider input boundaries."""

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="provider-fuzz-user",
            password=get_random_string(32),
        )
        self.client.force_login(user)
        self.profile, _ = LibraryProfile.objects.get_or_create(
            user=user,
            defaults={"session_fingerprint": get_session_fingerprint(self.client)},
        )

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
    @given(value=st.text(max_size=1024))
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
    @given(
        title=st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=240), st.lists(st.integers(), max_size=5)),
        artist=st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=240)),
        providers=st.one_of(
            st.none(),
            st.text(max_size=40),
            st.lists(st.one_of(st.none(), st.integers(), st.text(max_size=30)), max_size=8),
        ),
    )
    def test_library_search_json_fuzzer_never_returns_server_error(self, title, artist, providers):
        payload = {"title": title, "artist": artist, "providers": providers}
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
                data=json.dumps(payload),
                content_type="application/json",
            )
        self.assertIn(response.status_code, (200, 400))
        self.assertIsInstance(response.json(), dict)

    @FUZZ_SETTINGS
    @given(
        tracks=st.lists(
            st.one_of(
                st.none(),
                st.booleans(),
                st.integers(),
                st.text(max_size=80),
                st.dictionaries(
                    st.text(max_size=20),
                    st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=80), st.lists(st.integers(), max_size=4)),
                    max_size=8,
                ),
            ),
            max_size=12,
        )
    )
    def test_malformed_spotify_search_results_are_contained_as_provider_status(self, tracks):
        provider = Mock()
        provider.search_tracks.return_value = tracks
        with patch("transfer.library_views._spotify_access", return_value=(provider, "test-token")):
            response = self.client.post(
                reverse("library_track_search"),
                data=json.dumps({"title": "Fuzz title", "artist": "Fuzz artist", "providers": ["spotify"]}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsInstance(payload["results"], list)
        self.assertIn("spotify", payload["statuses"])
