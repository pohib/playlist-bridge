# ruff: noqa: I001
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import reverse

from transfer.models import AdminAuditEvent, UserSecurityEvent


TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "login-throttle-tests",
    }
}


@override_settings(CACHES=TEST_CACHES)
class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="staff-login",
            password="Correct-password-123!",
            is_staff=True,
        )

    def tearDown(self):
        cache.clear()

    @staticmethod
    def _render_login(_request, _template, context, status=200):
        errors = " ".join(str(error) for error in context["form"].non_field_errors())
        return HttpResponse(errors, status=status)

    def _login(self, password, *, remote_addr="203.0.113.10", username="staff-login"):
        with patch("transfer.auth_views.render", side_effect=self._render_login):
            return self.client.post(
                reverse("login"),
                {"username": username, "password": password},
                REMOTE_ADDR=remote_addr,
            )

    def test_five_failed_attempts_temporarily_block_login_for_same_ip_and_username(self):
        for _ in range(5):
            response = self._login("wrong-password")
            self.assertEqual(response.status_code, 200)

        response = self._login("Correct-password-123!")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Слишком много неудачных попыток входа")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(
            AdminAuditEvent.objects.filter(action="auth.login_failed").count(),
            5,
        )
        self.assertEqual(
            AdminAuditEvent.objects.filter(action="auth.login_throttled").count(),
            1,
        )

    def test_successful_login_is_not_blocked_without_failed_attempts(self):
        response = self._login("Correct-password-123!")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("dashboard"))
        security_event = UserSecurityEvent.objects.get(user=self.user)\n        self.assertEqual(security_event.event_type, UserSecurityEvent.EventType.LOGIN_SUCCEEDED)\n        self.assertEqual(security_event.ip_address, "203.0.113.10")\n        event = AdminAuditEvent.objects.get(action="auth.login_succeeded")
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.target_id, str(self.user.pk))
        self.assertIn("ip_fingerprint", event.metadata)

    def test_failures_from_another_ip_do_not_lock_the_legitimate_client(self):
        for _ in range(5):
            self._login("wrong-password", remote_addr="203.0.113.11")

        response = self._login("Correct-password-123!", remote_addr="203.0.113.12")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("dashboard"))

    def test_throttle_message_does_not_disclose_whether_account_exists(self):
        for _ in range(5):
            self._login("wrong-password", username="not-a-real-account")

        response = self._login("wrong-password", username="not-a-real-account")
        self.assertContains(response, "Слишком много неудачных попыток входа")
        self.assertNotContains(response, "не существует")

    def test_failed_staff_login_audit_does_not_store_credentials_or_plaintext_ip(self):
        self._login("Never-store-this-password", remote_addr="203.0.113.77")
        security_event = UserSecurityEvent.objects.get(user=self.user)\n        self.assertEqual(security_event.ip_address, "203.0.113.77")\n        self.assertEqual(security_event.event_type, UserSecurityEvent.EventType.LOGIN_FAILED)\n        event = AdminAuditEvent.objects.get(action="auth.login_failed")
        self.assertIsNone(event.actor)
        self.assertEqual(event.target_id, str(self.user.pk))
        serialized = str(event.metadata)
        self.assertNotIn("Never-store-this-password", serialized)
        self.assertNotIn("staff-login", serialized)
        self.assertNotIn("203.0.113.77", serialized)
        self.assertEqual(event.metadata["reason"], "invalid_credentials")

    def test_audit_storage_failure_does_not_block_successful_staff_login(self):
        with patch(
            "transfer.services.auth_security_audit.AdminAuditEvent.objects.create",
            side_effect=RuntimeError("audit database unavailable"),
        ):
            response = self._login("Correct-password-123!")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
