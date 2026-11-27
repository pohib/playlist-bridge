from django.test import TestCase
from django.urls import reverse

from transfer.models import LibraryPlaylist, LibraryProfile, LibraryTrack
from transfer.services.library_presentation import (
    build_playlist_playback_tracks,
    build_track_playback_data,
    cover_proxy_url,
    prepare_library_playlist,
    prepare_playlist_detail_tracks,
)


class LibraryPresentationTests(TestCase):
    def setUp(self):
        self.profile = LibraryProfile.objects.create(session_fingerprint="a" * 64)
        self.playlist = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Presentation playlist",
            provider=LibraryPlaylist.Provider.VK,
        )

    def test_cover_proxy_url_is_empty_without_artwork(self):
        track = LibraryTrack.objects.create(
            playlist=self.playlist,
            title="No cover",
            artist="Artist",
        )
        self.assertEqual(cover_proxy_url(track), "")

    def test_cover_proxy_url_uses_same_origin_endpoint(self):
        track = LibraryTrack.objects.create(
            playlist=self.playlist,
            title="With cover",
            artist="Artist",
            cover_url="https://images.example/cover.jpg",
        )
        self.assertEqual(
            cover_proxy_url(track),
            f"{reverse('library_cover_proxy')}?track_id={track.pk}",
        )

    def test_vk_track_contains_authenticated_stream_endpoints(self):
        track = LibraryTrack.objects.create(
            playlist=self.playlist,
            title="VK track",
            artist="Artist",
            external_id="10_20",
            source_provider=LibraryPlaylist.Provider.VK,
        )
        data = build_track_playback_data(track, self.playlist)
        self.assertEqual(data["provider"], LibraryPlaylist.Provider.VK)
        self.assertEqual(
            data["stream_url"],
            reverse("library_vk_track_audio", kwargs={"track_id": track.pk}),
        )
        self.assertEqual(
            data["stream_resolve_url"],
            reverse("library_vk_track_stream", kwargs={"track_id": track.pk}),
        )

    def test_local_track_uses_local_stream_and_disables_vk_proxy(self):
        track = LibraryTrack.objects.create(
            playlist=self.playlist,
            title="Local track",
            artist="Artist",
            audio_file="user-audio/test.mp3",
        )
        data = build_track_playback_data(track, self.playlist)
        self.assertEqual(data["provider"], "local")
        self.assertEqual(
            data["url"],
            reverse("library_stream_local_track", kwargs={"track_id": track.pk}),
        )
        self.assertEqual(data["stream_url"], "")
        self.assertEqual(data["stream_resolve_url"], "")

    def test_playlist_detail_serialization_attaches_cover_proxy_to_template_tracks(self):
        track = LibraryTrack.objects.create(
            playlist=self.playlist,
            title="Template artwork",
            artist="Artist",
            cover_url="https://images.example/cover.jpg",
        )
        rendered_track = prepare_playlist_detail_tracks(self.playlist)[0]
        self.assertEqual(
            rendered_track.cover_proxy_url,
            f"{reverse('library_cover_proxy')}?track_id={track.pk}",
        )

    def test_playlist_detail_serialization_preserves_track_order(self):
        first = LibraryTrack.objects.create(
            playlist=self.playlist, title="First", artist="Artist", position=1,
        )
        second = LibraryTrack.objects.create(
            playlist=self.playlist, title="Second", artist="Artist", position=2,
        )
        data = build_playlist_playback_tracks(self.playlist)
        self.assertEqual([item["title"] for item in data], ["First", "Second"])
        self.assertEqual(data[0]["id"], first.external_id)
        self.assertEqual(data[1]["id"], second.external_id)

    def test_library_playlist_preparation_attaches_cover_and_player_data(self):
        track = LibraryTrack.objects.create(
            playlist=self.playlist,
            title="Artwork track",
            artist="Artist",
            cover_url="https://images.example/cover.jpg",
        )
        prepared = prepare_library_playlist(self.playlist)
        self.assertEqual(prepared.playback_id, f"library-playback-{self.playlist.pk}")
        self.assertEqual(
            prepared.cover_proxy_url,
            f"{reverse('library_cover_proxy')}?track_id={track.pk}",
        )
        self.assertEqual(prepared.playback_data[0]["cover"], prepared.cover_proxy_url)
