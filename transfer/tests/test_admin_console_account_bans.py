from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from transfer.models import AdminAuditEvent, UserAccountBan


class AdminConsoleAccountBanTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_superuser(
            username="account-ban-admin", email="admin@example.test", password="test-password"
        )
        self.target = user_model.objects.create_user(
            username="account-ban-target", password="test-password"
        )
        self.client.force_login(self.admin)

    def test_create_temporary_account_ban_and_audit_it(self):
        response = self.client.post(
            reverse("admin_console_create_account_ban", args=[self.target.pk]),
            {"reason": "Нарушение правил", "duration_hours": "12"},
        )
        self.assertRedirects(
            response, reverse("admin_console_user_detail", args=[self.target.pk]),
            fetch_redirect_response=False,
        )
        ban = UserAccountBan.objects.get(user=self.target)
        self.assertEqual(ban.reason, "Нарушение правил")
        self.assertEqual(ban.created_by, self.admin)
        self.assertGreater(ban.expires_at, timezone.now())
        self.assertTrue(ban.is_active)
        self.assertTrue(AdminAuditEvent.objects.filter(action="user.account_banned", target_id=str(self.target.pk)).exists())

    def test_empty_reason_and_invalid_duration_are_rejected(self):
        url = reverse("admin_console_create_account_ban", args=[self.target.pk])
        self.client.post(url, {"reason": " ", "duration_hours": ""})
        self.assertFalse(UserAccountBan.objects.filter(user=self.target).exists())
        self.client.post(url, {"reason": "Причина", "duration_hours": "9000"})
        self.assertFalse(UserAccountBan.objects.filter(user=self.target).exists())

    def test_permanent_ban_can_be_revoked_without_deleting_history(self):
        ban = UserAccountBan.objects.create(
            user=self.target, reason="Проверка", created_by=self.admin
        )
        response = self.client.post(
            reverse("admin_console_revoke_account_ban", args=[self.target.pk, ban.pk])
        )
        self.assertRedirects(
            response, reverse("admin_console_user_detail", args=[self.target.pk]),
            fetch_redirect_response=False,
        )
        ban.refresh_from_db()
        self.assertEqual(ban.revoked_by, self.admin)
        self.assertIsNotNone(ban.revoked_at)
        self.assertFalse(ban.is_active)
        self.assertTrue(UserAccountBan.objects.filter(pk=ban.pk).exists())
        self.assertTrue(AdminAuditEvent.objects.filter(action="user.account_ban_revoked", target_id=str(self.target.pk)).exists())

    def test_expired_ban_is_inactive_without_a_cleanup_job(self):
        ban = UserAccountBan.objects.create(
            user=self.target, reason="Истёкшее ограничение", created_by=self.admin,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertFalse(ban.is_active)

    def test_cannot_ban_self_or_superuser(self):
        own_url = reverse("admin_console_create_account_ban", args=[self.admin.pk])
        self.assertEqual(self.client.post(own_url, {"reason": "test"}).status_code, 403)
        other_admin = get_user_model().objects.create_superuser(
            username="protected-admin", email="protected@example.test", password="test-password"
        )
        protected_url = reverse("admin_console_create_account_ban", args=[other_admin.pk])
        self.assertEqual(self.client.post(protected_url, {"reason": "test"}).status_code, 403)
        self.assertFalse(UserAccountBan.objects.exists())

    def test_staff_without_change_user_permission_cannot_create_ban(self):
        staff = get_user_model().objects.create_user(
            username="read-only-staff", password="test-password", is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.post(
            reverse("admin_console_create_account_ban", args=[self.target.pk]),
            {"reason": "Неавторизованное действие"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserAccountBan.objects.exists())
