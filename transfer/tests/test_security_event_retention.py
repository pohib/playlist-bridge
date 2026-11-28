from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from transfer.models import UserSecurityEvent


class SecurityEventRetentionTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="retention-user", password="test")
        self.expired = UserSecurityEvent.objects.create(
            user=user,
            username_snapshot=user.get_username(),
            event_type=UserSecurityEvent.EventType.LOGIN_FAILED,
            ip_address="203.0.113.20",
        )
        self.current = UserSecurityEvent.objects.create(
            user=user,
            username_snapshot=user.get_username(),
            event_type=UserSecurityEvent.EventType.LOGIN_SUCCEEDED,
            ip_address="203.0.113.21",
        )
        UserSecurityEvent.objects.filter(pk=self.expired.pk).update(
            created_at=timezone.now() - timedelta(days=100)
        )

    @override_settings(SECURITY_EVENT_RETENTION_DAYS=90)
    def test_command_deletes_only_events_older_than_retention_period(self):
        output = StringIO()
        call_command("purge_security_events", stdout=output)
        self.assertFalse(UserSecurityEvent.objects.filter(pk=self.expired.pk).exists())
        self.assertTrue(UserSecurityEvent.objects.filter(pk=self.current.pk).exists())
        self.assertIn("Удалено просроченных событий безопасности: 1", output.getvalue())

    def test_dry_run_does_not_delete_events(self):
        output = StringIO()
        call_command("purge_security_events", "--days=90", "--dry-run", stdout=output)
        self.assertTrue(UserSecurityEvent.objects.filter(pk=self.expired.pk).exists())
        self.assertIn("найдено просроченных событий — 1", output.getvalue())

    def test_invalid_retention_period_is_rejected(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("purge_security_events", "--days=0")
