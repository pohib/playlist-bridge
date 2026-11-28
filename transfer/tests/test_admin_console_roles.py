from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase
from django.urls import reverse

from transfer.models import AdminAuditEvent, TransferJob


class AdminConsoleRoleManagementTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.operator = self.user_model.objects.create_user(
            username="role-operator", password="test-password", is_staff=True
        )
        self.target = self.user_model.objects.create_user(
            username="role-target", password="test-password"
        )
        group_type = ContentType.objects.get_for_model(Group)
        user_type = ContentType.objects.get_for_model(self.user_model)
        self.operator.user_permissions.add(
            Permission.objects.get(content_type=group_type, codename="view_group"),
            Permission.objects.get(content_type=group_type, codename="change_group"),
            Permission.objects.get(content_type=user_type, codename="view_user"),
            Permission.objects.get(content_type=user_type, codename="change_user"),
        )
        job_type = ContentType.objects.get_for_model(TransferJob)
        self.safe_permission = Permission.objects.get(
            content_type=job_type, codename="view_transferjob"
        )
        self.dangerous_permission = Permission.objects.get(
            content_type=user_type, codename="change_user"
        )
        self.safe_group = Group.objects.create(name="Операторы")
        self.safe_group.permissions.add(self.safe_permission)
        self.dangerous_group = Group.objects.create(name="Привилегированная роль")
        self.dangerous_group.permissions.add(self.dangerous_permission)
        self.client.force_login(self.operator)

    def test_safe_role_can_be_edited_and_change_is_audited(self):
        response = self.client.post(
            reverse("admin_console_update_group", args=[self.safe_group.pk]),
            {"name": "Новые операторы", "permissions": []},
        )
        self.assertEqual(response.status_code, 302)
        self.safe_group.refresh_from_db()
        self.assertEqual(self.safe_group.name, "Новые операторы")
        self.assertFalse(self.safe_group.permissions.exists())
        event = AdminAuditEvent.objects.get(action="role.updated")
        self.assertEqual(event.actor, self.operator)
        self.assertEqual(event.target_id, str(self.safe_group.pk))
        self.assertEqual(event.metadata["before"]["name"], "Операторы")
        self.assertEqual(event.metadata["after"]["name"], "Новые операторы")

    def test_role_editor_rejects_non_allowlisted_permissions(self):
        response = self.client.post(
            reverse("admin_console_update_group", args=[self.safe_group.pk]),
            {"name": "Операторы", "permissions": [str(self.dangerous_permission.pk)]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(self.safe_group.permissions.values_list("pk", flat=True)),
            [self.safe_permission.pk],
        )
        self.assertFalse(AdminAuditEvent.objects.filter(action="role.updated").exists())

    def test_role_with_dangerous_permissions_cannot_be_edited(self):
        response = self.client.post(
            reverse("admin_console_update_group", args=[self.dangerous_group.pk]),
            {"name": "Попытка", "permissions": [str(self.safe_permission.pk)]},
        )
        self.assertEqual(response.status_code, 403)

    def test_group_edit_requires_change_group_permission(self):
        self.operator.user_permissions.remove(
            Permission.objects.get(
                content_type=ContentType.objects.get_for_model(Group),
                codename="change_group",
            )
        )
        response = self.client.post(
            reverse("admin_console_update_group", args=[self.safe_group.pk]),
            {"name": "Запрещено"},
        )
        self.assertEqual(response.status_code, 403)

    def test_group_edit_is_post_only(self):
        response = self.client.get(
            reverse("admin_console_update_group", args=[self.safe_group.pk])
        )
        self.assertEqual(response.status_code, 405)

    def test_user_can_receive_safe_group_and_change_is_audited(self):
        response = self.client.post(
            reverse("admin_console_update_user_groups", args=[self.target.pk]),
            {"groups": [str(self.safe_group.pk)]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(self.target.groups.all()), [self.safe_group])
        event = AdminAuditEvent.objects.get(action="user.groups_updated")
        self.assertEqual(event.actor, self.operator)
        self.assertEqual(event.target_id, str(self.target.pk))
        self.assertEqual(event.metadata["before"], [])
        self.assertEqual(event.metadata["after"][0]["name"], self.safe_group.name)

    def test_user_cannot_receive_group_with_dangerous_permissions(self):
        response = self.client.post(
            reverse("admin_console_update_user_groups", args=[self.target.pk]),
            {"groups": [str(self.dangerous_group.pk)]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.target.groups.exists())
        self.assertFalse(AdminAuditEvent.objects.filter(action="user.groups_updated").exists())

    def test_operator_cannot_change_own_groups(self):
        response = self.client.post(
            reverse("admin_console_update_user_groups", args=[self.operator.pk]),
            {"groups": [str(self.safe_group.pk)]},
        )
        self.assertEqual(response.status_code, 403)

    def test_superuser_groups_cannot_be_changed(self):
        superuser = self.user_model.objects.create_superuser(
            username="protected-root", email="root@example.test", password="test-password"
        )
        response = self.client.post(
            reverse("admin_console_update_user_groups", args=[superuser.pk]),
            {"groups": [str(self.safe_group.pk)]},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(superuser.groups.exists())

    def test_group_assignment_requires_both_permissions(self):
        self.operator.user_permissions.remove(
            Permission.objects.get(
                content_type=ContentType.objects.get_for_model(Group),
                codename="view_group",
            )
        )
        response = self.client.post(
            reverse("admin_console_update_user_groups", args=[self.target.pk]),
            {"groups": [str(self.safe_group.pk)]},
        )
        self.assertEqual(response.status_code, 403)

    def test_group_assignment_enforces_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.operator)
        response = csrf_client.post(
            reverse("admin_console_update_user_groups", args=[self.target.pk]),
            {"groups": [str(self.safe_group.pk)]},
        )
        self.assertEqual(response.status_code, 403)
