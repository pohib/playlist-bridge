from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from transfer.models import AdminAuditEvent


class AdminConsolePrivilegeTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.root = self.user_model.objects.create_superuser(
            username="privilege-root", email="root@example.test", password="root-password"
        )
        self.staff = self.user_model.objects.create_user(
            username="privilege-staff", password="staff-password", is_staff=True
        )
        self.client.force_login(self.root)

    def test_privilege_page_is_superuser_only(self):
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")):
            self.assertEqual(self.client.get(reverse("admin_console_privileges")).status_code, 200)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("admin_console_privileges")).status_code, 403)

    def test_staff_privilege_change_requires_password_and_is_audited(self):
        url = reverse("admin_console_update_privilege", args=[self.staff.pk])
        response = self.client.post(url, {
            "privilege": "staff", "enabled": "false", "password": "root-password",
        })
        self.assertEqual(response.status_code, 302)
        self.staff.refresh_from_db()
        self.assertFalse(self.staff.is_staff)
        event = AdminAuditEvent.objects.get(action="privilege.updated")
        self.assertEqual(event.actor, self.root)
        self.assertEqual(event.target_id, str(self.staff.pk))
        self.assertTrue(event.metadata["before"]["is_staff"])
        self.assertFalse(event.metadata["after"]["is_staff"])

    def test_superuser_grant_requires_explicit_phrase_and_sets_staff(self):
        url = reverse("admin_console_update_privilege", args=[self.staff.pk])
        response = self.client.post(url, {
            "privilege": "superuser", "enabled": "true", "password": "root-password",
            "confirmation": "ПОДТВЕРЖДАЮ",
        })
        self.assertEqual(response.status_code, 302)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_superuser)
        self.assertTrue(self.staff.is_staff)

    def test_invalid_password_and_missing_phrase_do_not_change_privileges(self):
        url = reverse("admin_console_update_privilege", args=[self.staff.pk])
        for payload in (
            {"privilege": "staff", "enabled": "true", "password": "wrong"},
            {"privilege": "superuser", "enabled": "true", "password": "root-password"},
        ):
            self.client.post(url, payload)
            self.staff.refresh_from_db()
            self.assertFalse(self.staff.is_superuser)

    def test_cannot_change_own_privileges_or_remove_last_active_superuser(self):
        own_url = reverse("admin_console_update_privilege", args=[self.root.pk])
        self.client.post(own_url, {
            "privilege": "superuser", "enabled": "false", "password": "root-password",
            "confirmation": "ПОДТВЕРЖДАЮ",
        })
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_superuser)

        other = self.user_model.objects.create_superuser(
            username="other-root", email="other@example.test", password="other-password"
        )
        other_url = reverse("admin_console_update_privilege", args=[other.pk])
        self.client.post(other_url, {
            "privilege": "superuser", "enabled": "false", "password": "root-password",
            "confirmation": "ПОДТВЕРЖДАЮ",
        })
        other.refresh_from_db()
        self.assertTrue(other.is_superuser)

    def test_cannot_remove_staff_flag_while_user_is_superuser(self):
        other = self.user_model.objects.create_superuser(
            username="other-root", email="other@example.test", password="other-password"
        )
        response = self.client.post(reverse("admin_console_update_privilege", args=[other.pk]), {
            "privilege": "staff", "enabled": "false", "password": "root-password",
        })
        self.assertEqual(response.status_code, 302)
        other.refresh_from_db()
        self.assertTrue(other.is_staff)
        self.assertTrue(other.is_superuser)
