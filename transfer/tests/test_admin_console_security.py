from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from transfer.models import AdminAuditEvent, UserSecurityEvent


class AdminConsoleSecurityTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.target = self.user_model.objects.create_user(username="security-target", password="test-password")
        self.staff = self.user_model.objects.create_user(username="security-staff", password="test-password", is_staff=True)
        user_type = ContentType.objects.get_for_model(self.user_model)
        self.staff.user_permissions.add(Permission.objects.get(content_type=user_type, codename="view_user"))
        self.superuser = self.user_model.objects.create_superuser(username="security-root", email="root@example.test", password="test-password")

    def test_only_superuser_sees_security_history_on_user_detail(self):
        UserSecurityEvent.objects.create(user=self.target, username_snapshot=self.target.get_username(), event_type=UserSecurityEvent.EventType.LOGIN_SUCCEEDED, ip_address="203.0.113.8", user_agent="Test browser")
        self.client.force_login(self.staff)
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")) as renderer:
            response = self.client.get(reverse("admin_console_user_detail", args=[self.target.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(renderer.call_args.args[2]["can_view_security"])
        self.assertEqual(renderer.call_args.args[2]["security_events"], [])
        self.assertFalse(AdminAuditEvent.objects.filter(action="security.user_events_viewed").exists())

    def test_superuser_sees_security_history_and_access_is_audited(self):
        event = UserSecurityEvent.objects.create(user=self.target, username_snapshot=self.target.get_username(), event_type=UserSecurityEvent.EventType.LOGIN_SUCCEEDED, ip_address="203.0.113.8", user_agent="Test browser")
        self.client.force_login(self.superuser)
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")) as renderer:
            response = self.client.get(reverse("admin_console_user_detail", args=[self.target.pk]))
        self.assertEqual(response.status_code, 200)
        context = renderer.call_args.args[2]
        self.assertTrue(context["can_view_security"])
        self.assertEqual(list(context["security_events"]), [event])
        audit = AdminAuditEvent.objects.get(action="security.user_events_viewed")
        self.assertEqual(audit.actor, self.superuser)
        self.assertEqual(audit.target_id, str(self.target.pk))

    def test_security_overview_is_superuser_only(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("admin_console_security")).status_code, 403)
        self.client.force_login(self.superuser)
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")):
            response = self.client.get(reverse("admin_console_security"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(AdminAuditEvent.objects.filter(action="security.events_viewed").exists())

    def test_security_filters_search_by_ip_and_event_type(self):
        UserSecurityEvent.objects.create(
            user=self.target, username_snapshot=self.target.get_username(),
            event_type=UserSecurityEvent.EventType.LOGIN_SUCCEEDED,
            ip_address="203.0.113.8", user_agent="Desktop browser",
        )
        UserSecurityEvent.objects.create(
            user=self.target, username_snapshot=self.target.get_username(),
            event_type=UserSecurityEvent.EventType.LOGIN_FAILED,
            ip_address="198.51.100.4", user_agent="Mobile browser",
        )
        self.client.force_login(self.superuser)
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")) as renderer:
            response = self.client.get(reverse("admin_console_security"), {
                "q": "198.51.100.4", "event_type": "login_failed",
            })
        self.assertEqual(response.status_code, 200)
        context = renderer.call_args.args[2]
        self.assertEqual(context["page"].paginator.count, 1)
        self.assertEqual(context["page"].object_list[0].ip_address, "198.51.100.4")
        self.assertEqual(context["event_type"], "login_failed")


    def test_security_search_can_filter_user_activity_by_route(self):
        UserSecurityEvent.objects.create(
            user=self.target,
            username_snapshot=self.target.get_username(),
            event_type=UserSecurityEvent.EventType.USER_ACTIVITY,
            http_method="POST",
            route_name="library_import_vk",
            response_status=422,
            request_id="12345678-1234-5678-1234-567812345678",
        )
        self.client.force_login(self.superuser)
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")) as renderer:
            response = self.client.get(reverse("admin_console_security"), {"q": "library_import_vk"})
        self.assertEqual(response.status_code, 200)
        page = renderer.call_args.args[2]["page"]
        self.assertEqual(page.paginator.count, 1)
        self.assertEqual(page.object_list[0].route_name, "library_import_vk")

    def test_security_views_are_not_cacheable(self):
        self.client.force_login(self.superuser)
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")):
            response = self.client.get(reverse("admin_console_security"))
        self.assertIn("no-store", response["Cache-Control"])
