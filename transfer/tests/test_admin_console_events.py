from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from transfer.models import AdminAuditEvent, TransferJob, UserSecurityEvent


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AdminConsoleEventCenterTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.superuser = user_model.objects.create_superuser(
            username="events-root", email="events@example.test", password="test-password"
        )
        self.staff = user_model.objects.create_user(
            username="events-staff", password="test-password", is_staff=True
        )

    def test_event_center_is_superuser_only(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("admin_console_events")).status_code, 403)
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("admin_console_events")).status_code, 200)

    def test_event_center_combines_admin_security_and_failed_transfer_events(self):
        AdminAuditEvent.objects.create(actor=self.superuser, action="role.created")
        UserSecurityEvent.objects.create(
            username_snapshot="suspicious-user",
            event_type=UserSecurityEvent.EventType.LOGIN_THROTTLED,
            ip_address="203.0.113.10",
        )
        TransferJob.objects.create(
            session_fingerprint="a" * 64,
            source_url="https://vk.com/music/playlist/1",
            status=TransferJob.Status.FAILED,
            error="internal failure text",
        )
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin_console_events"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Роль создана")
        self.assertContains(response, "Попытка входа ограничена")
        self.assertContains(response, "Перенос завершился ошибкой")
        self.assertNotContains(response, "internal failure text")
        self.assertNotContains(response, "203.0.113.10")

    def test_event_center_detects_stale_running_jobs(self):
        job = TransferJob.objects.create(
            session_fingerprint="b" * 64,
            source_url="https://vk.com/music/playlist/2",
            status=TransferJob.Status.RUNNING,
            started_at=timezone.now() - timedelta(minutes=8),
            heartbeat_at=timezone.now() - timedelta(minutes=8),
        )
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin_console_events"), {"category": "transfer"})
        self.assertContains(response, "Возможно, задача зависла")
        self.assertContains(response, str(job.pk))

    def test_event_center_filters_by_category_severity_and_query(self):
        UserSecurityEvent.objects.create(
            username_snapshot="blocked-account",
            event_type=UserSecurityEvent.EventType.LOGIN_THROTTLED,
        )
        UserSecurityEvent.objects.create(
            username_snapshot="normal-account",
            event_type=UserSecurityEvent.EventType.LOGIN_SUCCEEDED,
        )
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin_console_events"), {
            "category": "security", "severity": "danger", "q": "blocked-account",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "blocked-account")
        self.assertNotContains(response, "normal-account")

    def test_event_center_paginates_without_dropping_records(self):
        AdminAuditEvent.objects.bulk_create([
            AdminAuditEvent(actor=self.superuser, action=f"test.event.{index}")
            for index in range(55)
        ])
        self.client.force_login(self.superuser)
        first = self.client.get(reverse("admin_console_events"), {"category": "admin", "page": "1"})
        second = self.client.get(reverse("admin_console_events"), {"category": "admin", "page": "2"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.context["page"].paginator.count, 55)
        self.assertEqual(len(first.context["page"].object_list), 50)
        self.assertEqual(len(second.context["page"].object_list), 5)
