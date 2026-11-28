# ruff: noqa: I001
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import reverse


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

    def test_successful_login_is_not_blocked_without_failed_attempts(self):
        response = self._login("Correct-password-123!")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("dashboard"))

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
