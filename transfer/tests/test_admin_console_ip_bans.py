from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from transfer.models import AdminAuditEvent, UserIPBan


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AdminConsoleIPBanRegistryTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.staff = self.user_model.objects.create_user(
            username="ip-registry-staff", password="test-password", is_staff=True
        )
        self.root = self.user_model.objects.create_superuser(
            username="ip-registry-root", email="root@example.test", password="test-password"
        )

    def test_registry_is_superuser_only(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("admin_console_ip_bans")).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(reverse("admin_console_ip_bans")).status_code, 200)

    def test_registry_filters_active_expired_and_revoked_bans(self):
        active = UserIPBan.objects.create(
            ip_address="203.0.113.1", reason="Активная", created_by=self.root
        )
        expired = UserIPBan.objects.create(
            ip_address="203.0.113.2", reason="Истекшая", created_by=self.root,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        revoked = UserIPBan.objects.create(
            ip_address="203.0.113.3", reason="Снятая", created_by=self.root,
            revoked_at=timezone.now(), revoked_by=self.root,
        )
        self.client.force_login(self.root)
        for status, expected in (
            ("active", active), ("expired", expired), ("revoked", revoked),
        ):
            response = self.client.get(reverse("admin_console_ip_bans"), {"status": status})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(list(response.context["page"].object_list), [expected])

    def test_registry_searches_ip_reason_and_creator(self):
        ban = UserIPBan.objects.create(
            ip_address="198.51.100.77", reason="Подозрительная активность", created_by=self.root
        )
        self.client.force_login(self.root)
        response = self.client.get(reverse("admin_console_ip_bans"), {"q": "198.51.100.77"})
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertEqual(response.context["page"].object_list[0], ban)

    def test_create_ip_ban_validates_input_and_audits(self):
        self.client.force_login(self.root)
        invalid = self.client.post(reverse("admin_console_create_ip_ban"), {
            "ip_address": "not-an-ip", "reason": "Тест",
        })
        self.assertEqual(invalid.status_code, 302)
        self.assertFalse(UserIPBan.objects.exists())
        response = self.client.post(reverse("admin_console_create_ip_ban"), {
            "ip_address": "203.0.113.25", "reason": "Подозрительная активность",
            "duration_hours": "24",
        })
        self.assertEqual(response.status_code, 302)
        ban = UserIPBan.objects.get(ip_address="203.0.113.25")
        self.assertEqual(ban.created_by, self.root)
        self.assertGreater(ban.expires_at, timezone.now())
        self.assertTrue(AdminAuditEvent.objects.filter(
            actor=self.root, action="security.ip_banned", target_id=str(ban.pk)
        ).exists())

    def test_revoke_ip_ban_records_actor_and_timestamp(self):
        ban = UserIPBan.objects.create(
            ip_address="203.0.113.55", reason="Тест", created_by=self.root
        )
        self.client.force_login(self.root)
        response = self.client.post(
            reverse("admin_console_revoke_ip_ban_global", args=[ban.pk])
        )
        self.assertEqual(response.status_code, 302)
        ban.refresh_from_db()
        self.assertEqual(ban.revoked_by, self.root)
        self.assertIsNotNone(ban.revoked_at)
        self.assertTrue(AdminAuditEvent.objects.filter(
            actor=self.root, action="security.ip_ban_revoked", target_id=str(ban.pk)
        ).exists())

    def test_staff_cannot_create_or_revoke_ip_bans(self):
        ban = UserIPBan.objects.create(
            ip_address="203.0.113.99", reason="Тест", created_by=self.root
        )
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(reverse("admin_console_create_ip_ban"), {
            "ip_address": "203.0.113.100", "reason": "Тест",
        }).status_code, 403)
        self.assertEqual(self.client.post(
            reverse("admin_console_revoke_ip_ban_global", args=[ban.pk])
        ).status_code, 403)
        ban.refresh_from_db()
        self.assertIsNone(ban.revoked_at)



    def test_repeated_ip_ban_keeps_previous_history(self):
        previous = UserIPBan.objects.create(
            ip_address="203.0.113.25",
            reason="Первоначальная причина",
            created_by=self.root,
            revoked_at=timezone.now(),
            revoked_by=self.root,
        )
        self.client.force_login(self.root)
        response = self.client.post(reverse("admin_console_create_ip_ban"), {
            "ip_address": "203.0.113.25",
            "reason": "Повторная блокировка",
            "duration_hours": "12",
        })
        self.assertEqual(response.status_code, 302)
        bans = UserIPBan.objects.filter(ip_address="203.0.113.25").order_by("created_at")
        self.assertEqual(bans.count(), 2)
        previous.refresh_from_db()
        self.assertEqual(previous.reason, "Первоначальная причина")
        self.assertIsNotNone(previous.revoked_at)
        current = bans.latest("created_at")
        self.assertEqual(current.reason, "Повторная блокировка")
        self.assertIsNone(current.revoked_at)
        self.assertEqual(
            AdminAuditEvent.objects.filter(
                actor=self.root, action="security.ip_banned",
                target_id=str(current.pk),
            ).count(),
            1,
        )

    def test_deactivated_account_session_is_rejected_on_next_request(self):
        target = self.user_model.objects.create_user(
            username="account-ban-target", password="test-password"
        )
        operator = self.user_model.objects.create_user(
            username="account-ban-operator", password="test-password", is_staff=True
        )
        user_type = ContentType.objects.get_for_model(self.user_model)
        operator.user_permissions.add(
            Permission.objects.get(content_type=user_type, codename="change_user")
        )
        target_client = self.client_class()
        target_client.force_login(target)
        operator_client = self.client_class()
        operator_client.force_login(operator)

        response = operator_client.post(
            reverse("admin_console_toggle_user", args=[target.pk])
        )
        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertFalse(target.is_active)

        protected_response = target_client.get(reverse("profile"))
        self.assertEqual(protected_response.status_code, 302)
        self.assertIn(reverse("login"), protected_response.url)
