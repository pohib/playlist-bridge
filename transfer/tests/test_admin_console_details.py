from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from transfer.models import LibraryPlaylist, LibraryProfile, LibraryTrack, TransferJob


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AdminConsoleDetailTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="library-owner", password="test-password")
        self.staff = user_model.objects.create_user(username="library-auditor", password="test-password", is_staff=True)
        self.profile = LibraryProfile.objects.create(user=self.owner, session_fingerprint="private-session-fingerprint")
        self.playlist = LibraryPlaylist.objects.create(profile=self.profile, title="Private playlist", provider=LibraryPlaylist.Provider.VK)
        LibraryTrack.objects.create(playlist=self.playlist, title="Track title", artist="Track artist", external_id="private-external-id")
        self.job = TransferJob.objects.create(
            session_fingerprint=self.profile.session_fingerprint,
            source_url="https://vk.com/music/playlist/123",
            target_playlist="Target playlist",
            checkpoint={"access_token": "must-not-be-rendered"},
            result={"refresh_token": "must-not-be-rendered"},
        )

    def grant(self, codename, model):
        content_type = ContentType.objects.get_for_model(model)
        self.staff.user_permissions.add(Permission.objects.get(content_type=content_type, codename=codename))

    def test_library_detail_requires_library_permission(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin_console_library_detail", args=[self.profile.pk]))
        self.assertEqual(response.status_code, 403)

    def test_library_detail_shows_collection_without_private_fingerprints(self):
        self.grant("view_libraryprofile", LibraryProfile)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin_console_library_detail", args=[self.profile.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Private playlist")
        self.assertContains(response, "Track title")
        self.assertNotContains(response, "private-session-fingerprint")
        self.assertNotContains(response, "private-external-id")


    def test_jobs_overview_reports_queue_backlog_and_stale_workers(self):
        now = timezone.now()
        TransferJob.objects.create(
            session_fingerprint="queued-job-fingerprint",
            source_url="https://vk.com/music/playlist/queued",
            status=TransferJob.Status.QUEUED,
        )
        TransferJob.objects.create(
            session_fingerprint="running-job-fingerprint",
            source_url="https://vk.com/music/playlist/running",
            status=TransferJob.Status.RUNNING,
            started_at=now - timedelta(minutes=20),
            heartbeat_at=now - timedelta(minutes=10),
        )
        TransferJob.objects.create(
            session_fingerprint="failed-job-fingerprint",
            source_url="https://vk.com/music/playlist/failed",
            status=TransferJob.Status.FAILED,
            finished_at=now - timedelta(hours=2),
        )
        TransferJob.objects.create(
            session_fingerprint="successful-job-fingerprint",
            source_url="https://vk.com/music/playlist/success",
            status=TransferJob.Status.SUCCEEDED,
        )
        self.grant("view_transferjob", TransferJob)
        self.client.force_login(self.staff)

        response = self.client.get(reverse("admin_console_jobs"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["job_summary"], {
            "queued": 1,
            "running": 1,
            "succeeded": 1,
            "failed": 1,
            "stale_running": 1,
            "awaiting_dispatch": 1,
            "failed_24h": 1,
        })
        self.assertContains(response, "Без heartbeat 5+ мин")
        self.assertContains(response, "Ожидают отправки")

    def test_job_detail_requires_job_permission(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin_console_job_detail", args=[self.job.pk]))
        self.assertEqual(response.status_code, 403)

    def test_job_detail_does_not_render_checkpoint_or_result_payloads(self):
        self.grant("view_transferjob", TransferJob)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin_console_job_detail", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Target playlist")
        self.assertContains(response, "library-owner")
        self.assertNotContains(response, "must-not-be-rendered")
        self.assertNotContains(response, "private-session-fingerprint")
