from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
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

    def test_user_list_filters_by_status_and_staff_access(self):
        content_type = ContentType.objects.get_for_model(self.user_model)
        self.staff_viewer.user_permissions.add(
            Permission.objects.get(content_type=content_type, codename="view_user")
        )
        self.user_model.objects.create_user(username="inactive-member", is_active=False)
        self.user_model.objects.create_user(username="active-member")
        self.client.force_login(self.staff_viewer)
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")) as renderer:
            response = self.client.get(reverse("admin_console_users"), {
                "status": "active", "access": "users",
            })
        self.assertEqual(response.status_code, 200)
        page = renderer.call_args.args[2]["page"]
        self.assertEqual(page.paginator.count, 2)
        self.assertTrue(all(item.is_active and not item.is_staff for item in page.object_list))

    def test_user_detail_requires_user_view_permission(self):
        self.client.force_login(self.staff_viewer)
        response = self.client.get(reverse("admin_console_user_detail", args=[self.regular_user.pk]))
        self.assertEqual(response.status_code, 403)

    def test_user_detail_is_available_to_staff_with_user_view_permission(self):
        content_type = ContentType.objects.get_for_model(self.user_model)
        self.staff_viewer.user_permissions.add(
            Permission.objects.get(content_type=content_type, codename="view_user")
        )
        self.client.force_login(self.staff_viewer)
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")) as render_view:
            response = self.client.get(reverse("admin_console_user_detail", args=[self.regular_user.pk]))
        self.assertEqual(response.status_code, 200)
        context = render_view.call_args.args[2]
        self.assertEqual(context["account"].pk, self.regular_user.pk)
        self.assertFalse(context["can_toggle_account"])

    def test_user_detail_rejects_regular_users(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse("admin_console_user_detail", args=[self.regular_user.pk]))
        self.assertEqual(response.status_code, 302)

    
    def test_groups_page_requires_group_view_permission(self):
        self.client.force_login(self.staff_viewer)
        self.assertEqual(self.client.get(reverse("admin_console_groups")).status_code, 403)

    def test_group_creation_only_accepts_allowlisted_read_permissions(self):
        content_type = ContentType.objects.get_for_model(Group)
        self.staff_viewer.user_permissions.add(
            Permission.objects.get(content_type=content_type, codename="add_group"),
            Permission.objects.get(content_type=content_type, codename="view_group"),
        )
        self.client.force_login(self.staff_viewer)
        safe_permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(TransferJob),
            codename="view_transferjob",
        )
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")):
            response = self.client.post(reverse("admin_console_create_group"), {
                "name": "Операторы очереди",
                "permissions": [str(safe_permission.pk)],
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("admin_console_groups"))
        group = Group.objects.get(name="Операторы очереди")
        self.assertEqual(list(group.permissions.values_list("pk", flat=True)), [safe_permission.pk])

    def test_group_creation_rejects_mutating_permissions(self):
        content_type = ContentType.objects.get_for_model(Group)
        self.staff_viewer.user_permissions.add(
            Permission.objects.get(content_type=content_type, codename="add_group"),
            Permission.objects.get(content_type=content_type, codename="view_group"),
        )
        self.client.force_login(self.staff_viewer)
        dangerous = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(self.user_model),
            codename="change_user",
        )
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")):
            response = self.client.post(reverse("admin_console_create_group"), {
                "name": "Опасная роль",
                "permissions": [str(dangerous.pk)],
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("admin_console_groups"))
        self.assertFalse(Group.objects.filter(name="Опасная роль").exists())

    def test_group_creation_requires_add_group_permission(self):
        self.client.force_login(self.staff_viewer)
        response = self.client.post(reverse("admin_console_create_group"), {
            "name": "Нет доступа",
            "permissions": [],
        })
        self.assertEqual(response.status_code, 403)


    def test_staff_dashboard_does_not_expose_superuser_operational_analytics(self):
        self.client.force_login(self.staff_viewer)
        with patch("transfer.admin_console_views.render", return_value=HttpResponse("ok")) as renderer:
            response = self.client.get(reverse("admin_console"))
        self.assertEqual(response.status_code, 200)
        context = renderer.call_args.args[2]
        self.assertFalse(context["can_view_operational_analytics"])
        self.assertIsNone(context["request_error_counts"])
        self.assertEqual(context["top_error_routes"], [])
        self.assertEqual(context["recent_request_errors"], [])

    def test_staff_panel_responses_are_not_cacheable(self):
        self.client.force_login(self.staff_viewer)
        with patch(
            "transfer.admin_console_views.render",
            return_value=HttpResponse("ok"),
        ):
            response = self.client.get(reverse("admin_console"))
        self.assertIn("no-store", response["Cache-Control"])
