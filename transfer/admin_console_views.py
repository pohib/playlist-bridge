"""Staff-only, permission-scoped Playlist Bridge control panel."""
from functools import wraps
from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import AdminAuditEvent, LibraryPlaylist, LibraryProfile, TransferJob, UserSecurityEvent


def _staff(view):
    @wraps(view)
    @staff_member_required(login_url="login")
    def wrapped(request, *args, **kwargs):
        return view(request, *args, **kwargs)
    return never_cache(wrapped)


@_staff
@require_GET
def console_dashboard(request):
    permissions = {
        "can_view_users": request.user.has_perm("auth.view_user"),
        "can_view_library": request.user.has_perm("transfer.view_libraryprofile"),
        "can_view_jobs": request.user.has_perm("transfer.view_transferjob"),
        "can_view_audit": request.user.has_perm("transfer.view_adminevent"),
    }
    if not any(permissions.values()):
        raise PermissionDenied
    context = {
        **permissions,
        "user_count": get_user_model().objects.count() if permissions["can_view_users"] else None,
        "profile_count": LibraryProfile.objects.count() if permissions["can_view_library"] else None,
        "playlist_count": LibraryPlaylist.objects.count() if permissions["can_view_library"] else None,
        "queued_count": TransferJob.objects.filter(status=TransferJob.Status.QUEUED).count() if permissions["can_view_jobs"] else None,
        "running_count": TransferJob.objects.filter(status=TransferJob.Status.RUNNING).count() if permissions["can_view_jobs"] else None,
        "failed_count": TransferJob.objects.filter(status=TransferJob.Status.FAILED).count() if permissions["can_view_jobs"] else None,
        "recent_jobs": TransferJob.objects.only(
            "id", "status", "progress", "total", "created_at", "error"
        )[:8] if permissions["can_view_jobs"] else [],
        "recent_events": AdminAuditEvent.objects.select_related("actor")[:6] if permissions["can_view_audit"] else [],
    }
    return render(request, "transfer/admin_console/dashboard.html", context)


@_staff
@permission_required("auth.view_user", raise_exception=True)
@require_GET
def console_users(request):
    query = (request.GET.get("q") or "").strip()[:100]
    users = get_user_model().objects.all().order_by("-date_joined")
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
    page = Paginator(users, 25).get_page(request.GET.get("page"))
    return render(request, "transfer/admin_console/users.html", {
        "page": page,
        "query": query,
        "can_change_users": request.user.has_perm("auth.change_user"),
    })

@_staff
@permission_required("auth.view_user", raise_exception=True)
@require_GET
def console_user_detail(request, user_id):
    user_model = get_user_model()
    account = get_object_or_404(
        user_model.objects.prefetch_related("groups", "user_permissions__content_type"),
        pk=user_id,
    )
    audit_events = AdminAuditEvent.objects.filter(
        target_type=user_model._meta.label,
        target_id=str(account.pk),
    ).select_related("actor")[:20]
    action_labels = {
        "user.activated": "Пользователь активирован",
        "user.deactivated": "Пользователь отключён",
        "user.groups_updated": "Группы пользователя изменены",
        "auth.login_failed": "Неудачная попытка входа сотрудника",
        "auth.login_throttled": "Попытка входа заблокирована ограничителем",
        "auth.login_succeeded": "Сотрудник вошёл в систему",
        "security.user_events_viewed": "Просмотрена история безопасности пользователя",
        "security.events_viewed": "Просмотрен журнал безопасности",
    }
    for event in audit_events:
        event.action_label = action_labels.get(event.action, "Системное действие")
    can_change_users = request.user.has_perm("auth.change_user")
    current_groups = list(account.groups.prefetch_related("permissions__content_type").order_by("name"))
    has_unsafe_groups = any(not _is_safe_group(group) for group in current_groups)
    for group in current_groups:
        group.is_safe_role = _is_safe_group(group)
    can_manage_groups = (
        can_change_users
        and request.user.has_perm("auth.view_group")
        and account.pk != request.user.pk
        and not account.is_superuser
        and not has_unsafe_groups
    )
    safe_groups = Group.objects.prefetch_related("permissions__content_type").order_by("name")
    safe_groups = [group for group in safe_groups if _is_safe_group(group)]
    security_events = []
    if request.user.is_superuser:
        security_events = list(UserSecurityEvent.objects.filter(user=account)[:30])
        AdminAuditEvent.objects.create(
            actor=request.user,
            action="security.user_events_viewed",
            target_type=user_model._meta.label,
            target_id=str(account.pk),
            metadata={"event_count": len(security_events)},
        )
    return render(request, "transfer/admin_console/user_detail.html", {
        "account": account,
        "security_events": security_events,
        "can_view_security": request.user.is_superuser,
        "groups": current_groups,
        "safe_groups": safe_groups,
        "has_unsafe_groups": has_unsafe_groups,
        "can_manage_groups": can_manage_groups,
        "permissions": account.user_permissions.all().order_by(
            "content_type__app_label", "codename"
        ),
        "audit_events": audit_events,
        "can_toggle_account": (
            can_change_users and account.pk != request.user.pk and not account.is_superuser
        ),
    })


@_staff
@permission_required("auth.change_user", raise_exception=True)
@require_POST
def console_toggle_user(request, user_id):
    target = get_object_or_404(get_user_model(), pk=user_id)
    if target.pk == request.user.pk or target.is_superuser:
        raise PermissionDenied("Нельзя менять состояние собственной или superuser-учётной записи.")
    target.is_active = not target.is_active
    target.save(update_fields=["is_active"])
    AdminAuditEvent.objects.create(
        actor=request.user,
        action="user.activated" if target.is_active else "user.deactivated",
        target_type=get_user_model()._meta.label,
        target_id=str(target.pk),
        metadata={"username": target.get_username(), "is_active": target.is_active},
    )
    messages.success(
        request,
        f"Учётная запись {target.get_username()} "
        f"{'активирована' if target.is_active else 'деактивирована'}.",
    )
    return redirect("admin_console_users")


@_staff
@permission_required("transfer.view_transferjob", raise_exception=True)
@require_GET
def console_jobs(request):
    status = (request.GET.get("status") or "").strip()
    query = (request.GET.get("q") or "").strip()[:100]
    jobs = TransferJob.objects.all()
    valid_statuses = {value for value, _label in TransferJob.Status.choices}
    if status in valid_statuses:
        jobs = jobs.filter(status=status)
    else:
        status = ""
    if query:
        jobs = jobs.filter(Q(source_url__icontains=query) | Q(error__icontains=query))
    page = Paginator(jobs, 25).get_page(request.GET.get("page"))
    for job in page.object_list:
        job.source_host = urlsplit(job.source_url).hostname or "—"
    return render(request, "transfer/admin_console/jobs.html", {
        "page": page, "status": status, "query": query,
        "statuses": TransferJob.Status.choices,
    })


@_staff
@permission_required("transfer.view_libraryprofile", raise_exception=True)
@require_GET
def console_library(request):
    profiles = LibraryProfile.objects.select_related("user").annotate(
        playlists_count=Count("playlists", distinct=True),
        tracks_count=Count("playlists__tracks", distinct=True),
    ).order_by("-updated_at")
    page = Paginator(profiles, 25).get_page(request.GET.get("page"))
    return render(request, "transfer/admin_console/library.html", {"page": page})


@_staff
@permission_required("transfer.view_adminevent", raise_exception=True)
@require_GET
def console_audit(request):
    page = Paginator(
        AdminAuditEvent.objects.select_related("actor"), 50
    ).get_page(request.GET.get("page"))
    action_labels = {
        "user.activated": "Пользователь активирован",
        "user.deactivated": "Пользователь отключён",
        "role.created": "Роль создана",
        "role.updated": "Роль изменена",
        "user.groups_updated": "Группы пользователя изменены",
        "auth.login_failed": "Неудачная попытка входа сотрудника",
        "auth.login_throttled": "Попытка входа заблокирована ограничителем",
        "auth.login_succeeded": "Сотрудник вошёл в систему",
        "security.user_events_viewed": "Просмотрена история безопасности пользователя",
        "security.events_viewed": "Просмотрен журнал безопасности",
    }
    for event in page.object_list:
        event.action_label = action_labels.get(event.action, "Системное действие")
    return render(request, "transfer/admin_console/audit.html", {"page": page})



@_staff
@require_GET
def console_security(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    events = list(UserSecurityEvent.objects.select_related("user")[:100])
    AdminAuditEvent.objects.create(
        actor=request.user,
        action="security.events_viewed",
        target_type="transfer.UserSecurityEvent",
        metadata={"event_count": len(events)},
    )
    return render(request, "transfer/admin_console/security.html", {"events": events})



@_staff
@require_GET
def console_privileges(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    user_model = get_user_model()
    accounts = user_model.objects.filter(
        Q(is_staff=True) | Q(is_superuser=True)
    ).order_by("-is_superuser", "-is_staff", "username")
    return render(request, "transfer/admin_console/privileges.html", {
        "accounts": accounts,
        "active_superuser_count": user_model.objects.filter(
            is_superuser=True, is_active=True
        ).count(),
    })


@_staff
@require_POST
def console_update_privilege(request, user_id):
    if not request.user.is_superuser:
        raise PermissionDenied
    user_model = get_user_model()
    privilege = (request.POST.get("privilege") or "").strip()
    enabled = request.POST.get("enabled") == "true"
    confirmation = (request.POST.get("confirmation") or "").strip()
    password = request.POST.get("password") or ""
    if privilege not in {"staff", "superuser"}:
        messages.error(request, "Выбран неизвестный тип привилегии.")
        return redirect("admin_console_privileges")
    if not check_password(password, request.user.password):
        messages.error(request, "Не удалось подтвердить пароль суперпользователя.")
        return redirect("admin_console_privileges")
    if privilege == "superuser" and confirmation != "ПОДТВЕРЖДАЮ":
        messages.error(request, "Для изменения прав суперпользователя введи фразу «ПОДТВЕРЖДАЮ».")
        return redirect("admin_console_privileges")
    if str(user_id) == str(request.user.pk):
        messages.error(request, "Нельзя изменять собственные привилегии.")
        return redirect("admin_console_privileges")

    with transaction.atomic():
        list(user_model.objects.select_for_update().filter(is_superuser=True, is_active=True))
        target = get_object_or_404(user_model.objects.select_for_update(), pk=user_id)
        before = {"is_staff": target.is_staff, "is_superuser": target.is_superuser}
        if privilege == "staff":
            target.is_staff = enabled
        elif enabled:
            target.is_superuser = True
            target.is_staff = True
        else:
            active_superusers = user_model.objects.filter(
                is_superuser=True, is_active=True
            ).count()
            if target.is_active and target.is_superuser and active_superusers <= 1:
                messages.error(request, "Нельзя снять права: в системе должен остаться хотя бы один активный суперпользователь.")
                return redirect("admin_console_privileges")
            target.is_superuser = False
        after = {"is_staff": target.is_staff, "is_superuser": target.is_superuser}
        if before == after:
            messages.info(request, "Указанные привилегии уже имеют выбранное состояние.")
            return redirect("admin_console_privileges")
        target.save(update_fields=["is_staff", "is_superuser"])
        AdminAuditEvent.objects.create(
            actor=request.user,
            action="privilege.updated",
            target_type=user_model._meta.label,
            target_id=str(target.pk),
            metadata={
                "username": target.get_username(),
                "privilege": privilege,
                "before": before,
                "after": after,
            },
        )
    messages.success(request, f"Привилегии пользователя {target.get_username()} обновлены.")
    return redirect("admin_console_privileges")


def _safe_role_permissions():
    """Only expose read-only permissions for explicitly supported admin sections."""
    return Permission.objects.filter(
        content_type__app_label__in=("auth", "transfer"),
        content_type__model__in=(
            "user", "libraryprofile", "libraryplaylist", "transferjob", "adminevent"
        ),
        codename__startswith="view_",
    ).select_related("content_type").order_by(
        "content_type__app_label", "content_type__model", "name"
    )


@_staff
@permission_required("auth.view_group", raise_exception=True)
@require_GET
def console_groups(request):
    from django.contrib.auth.models import Group

    groups = list(Group.objects.annotate(
        members_count=Count("user", distinct=True)
    ).prefetch_related("permissions__content_type").order_by("name"))
    for group in groups:
        group.is_safe_role = _is_safe_group(group)
    return render(request, "transfer/admin_console/groups.html", {
        "groups": groups,
        "safe_permissions": _safe_role_permissions(),
        "can_create_groups": request.user.has_perm("auth.add_group"),
        "can_edit_groups": request.user.has_perm("auth.change_group"),
    })


@_staff
@permission_required("auth.view_group", raise_exception=True)
@permission_required("auth.add_group", raise_exception=True)
@require_POST
def console_create_group(request):
    from django.contrib.auth.models import Group

    name = (request.POST.get("name") or "").strip()[:150]
    selected_ids = request.POST.getlist("permissions")
    if not name:
        messages.error(request, "Укажите название роли.")
        return redirect("admin_console_groups")
    if Group.objects.filter(name__iexact=name).exists():
        messages.error(request, "Роль с таким названием уже существует.")
        return redirect("admin_console_groups")
    allowed = _safe_role_permissions()
    selected = allowed.filter(pk__in=selected_ids)
    if (
        not selected_ids
        or any(not value.isdecimal() for value in selected_ids)
        or selected.count() != len(set(selected_ids))
    ):
        messages.error(request, "Выберите только разрешённые права чтения.")
        return redirect("admin_console_groups")
    group = Group.objects.create(name=name)
    group.permissions.set(selected)
    AdminAuditEvent.objects.create(
        actor=request.user,
        action="role.created",
        target_type=Group._meta.label,
        target_id=str(group.pk),
        metadata={"name": group.name, "permission_count": selected.count()},
    )
    messages.success(request, f"Роль «{group.name}» создана.")
    return redirect("admin_console_groups")



def _is_safe_group(group):
    """A role is manageable only when every attached permission is allowlisted."""
    allowed_ids = _safe_role_permissions().values("pk")
    return not group.permissions.exclude(pk__in=allowed_ids).exists()


@_staff
@permission_required("auth.view_group", raise_exception=True)
@permission_required("auth.change_group", raise_exception=True)
@require_POST
def console_update_group(request, group_id):
    group = get_object_or_404(Group.objects.prefetch_related("permissions__content_type"), pk=group_id)
    if not _is_safe_group(group):
        raise PermissionDenied("Роль содержит права, которыми нельзя управлять через эту панель.")

    name = (request.POST.get("name") or "").strip()[:150]
    selected_ids = request.POST.getlist("permissions")
    if not name:
        messages.error(request, "Укажите название роли.")
        return redirect("admin_console_groups")
    if Group.objects.filter(name__iexact=name).exclude(pk=group.pk).exists():
        messages.error(request, "Роль с таким названием уже существует.")
        return redirect("admin_console_groups")
    if any(not value.isdecimal() for value in selected_ids) or len(selected_ids) != len(set(selected_ids)):
        messages.error(request, "Выберите только разрешённые права чтения.")
        return redirect("admin_console_groups")

    selected = _safe_role_permissions().filter(pk__in=selected_ids)
    if selected.count() != len(selected_ids):
        messages.error(request, "Выберите только разрешённые права чтения.")
        return redirect("admin_console_groups")

    before = {
        "name": group.name,
        "permissions": sorted(
            f"{item.content_type.app_label}.{item.codename}"
            for item in group.permissions.all()
        ),
    }
    with transaction.atomic():
        group.name = name
        group.save(update_fields=["name"])
        group.permissions.set(selected)
        after = {
            "name": group.name,
            "permissions": sorted(
                f"{item.content_type.app_label}.{item.codename}"
                for item in selected.select_related("content_type")
            ),
        }
        AdminAuditEvent.objects.create(
            actor=request.user,
            action="role.updated",
            target_type=Group._meta.label,
            target_id=str(group.pk),
            metadata={"before": before, "after": after},
        )
    messages.success(request, f"Роль «{group.name}» обновлена.")
    return redirect("admin_console_groups")


@_staff
@permission_required("auth.view_group", raise_exception=True)
@permission_required("auth.change_user", raise_exception=True)
@require_POST
def console_update_user_groups(request, user_id):
    user_model = get_user_model()
    account = get_object_or_404(
        user_model.objects.prefetch_related("groups__permissions__content_type"),
        pk=user_id,
    )
    if account.pk == request.user.pk or account.is_superuser:
        raise PermissionDenied("Нельзя изменять собственные роли или роли суперпользователя.")
    if any(not _is_safe_group(group) for group in account.groups.all()):
        raise PermissionDenied("У пользователя есть роль с расширенными правами. Требуется отдельная проверка.")

    selected_ids = request.POST.getlist("groups")
    if any(not value.isdecimal() for value in selected_ids) or len(selected_ids) != len(set(selected_ids)):
        messages.error(request, "Выберите только разрешённые роли.")
        return redirect("admin_console_user_detail", user_id=account.pk)

    selected = list(
        Group.objects.filter(pk__in=selected_ids).prefetch_related("permissions__content_type").order_by("name")
    )
    if len(selected) != len(selected_ids) or any(not _is_safe_group(group) for group in selected):
        messages.error(request, "Нельзя назначить роль с расширенными правами.")
        return redirect("admin_console_user_detail", user_id=account.pk)

    before = sorted(
        ({"id": group.pk, "name": group.name} for group in account.groups.all()),
        key=lambda item: item["id"],
    )
    after = sorted(
        ({"id": group.pk, "name": group.name} for group in selected),
        key=lambda item: item["id"],
    )
    with transaction.atomic():
        account.groups.set(selected)
        AdminAuditEvent.objects.create(
            actor=request.user,
            action="user.groups_updated",
            target_type=user_model._meta.label,
            target_id=str(account.pk),
            metadata={"before": before, "after": after},
        )
    messages.success(request, f"Группы пользователя {account.get_username()} обновлены.")
    return redirect("admin_console_user_detail", user_id=account.pk)
