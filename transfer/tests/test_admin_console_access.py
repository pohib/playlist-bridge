from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from transfer.models import TransferJob


class AdminConsoleAccessTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.regular_user = self.user_model.objects.create_user(
            username="regular", password="test-password"
        )
        self.staff_without_permissions = self.user_model.objects.create_user(
            username="staff-limited", password="test-password", is_staff=True
        )
        self.staff_viewer = self.user_model.objects.create_user(
            username="staff-viewer", password="test-password", is_staff=True
        )
        permission = self.staff_viewer.user_permissions
        content_type = ContentType.objects.get_for_model(TransferJob)
        permission.add(Permission.objects.get(
            content_type=content_type, codename="view_transferjob"
        ))

    def test_anonymous_user_cannot_open_control_panel(self):
        response = self.client.get(reverse("admin_console"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_regular_authenticated_user_cannot_open_control_panel(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse("admin_console"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_staff_without_permissions_cannot_open_control_panel(self):
        self.client.force_login(self.staff_without_permissions)
        response = self.client.get(reverse("admin_console"))
        self.assertEqual(response.status_code, 403)

    def test_staff_with_scoped_permission_can_open_only_authorized_section(self):
        self.client.force_login(self.staff_viewer)
        with patch(
            "transfer.admin_console_views.render",
            return_value=HttpResponse("ok"),
        ) as render_view:
            response = self.client.get(reverse("admin_console"))
        self.assertEqual(response.status_code, 200)
        context = render_view.call_args.args[2]
        self.assertTrue(context["can_view_jobs"])
        self.assertFalse(context["can_view_users"])
        self.assertFalse(context["can_view_library"])
        self.assertFalse(context["can_view_audit"])

    def test_staff_panel_responses_are_not_cacheable(self):
        self.client.force_login(self.staff_viewer)
        with patch(
            "transfer.admin_console_views.render",
            return_value=HttpResponse("ok"),
        ):
            response = self.client.get(reverse("admin_console"))
        self.assertIn("no-store", response["Cache-Control"])
