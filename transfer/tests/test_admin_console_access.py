from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


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
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from transfer.models import TransferJob

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
        response = self.client.get(reverse("admin_console"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Очередь и переносы")
        self.assertNotContains(response, "Пользователи")
        self.assertNotContains(response, "Музыкальные библиотеки")

    def test_staff_panel_responses_are_not_cacheable(self):
        self.client.force_login(self.staff_viewer)
        response = self.client.get(reverse("admin_console"))
        self.assertIn("no-store", response["Cache-Control"])
