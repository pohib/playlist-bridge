import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower


class AdminAuditEvent(models.Model):
    """Append-only record of privileged actions in the custom control panel."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="playlist_bridge_admin_events")
    action = models.CharField(max_length=80, db_index=True)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "событие панели управления"
        verbose_name_plural = "события панели управления"

    def __str__(self):
        return f"{self.action} · {self.created_at:%Y-%m-%d %H:%M}"


class UserSecurityEvent(models.Model):
    """Login telemetry visible only to superusers in the custom control panel."""
    class EventType(models.TextChoices):
        LOGIN_SUCCEEDED = "login_succeeded", "Успешный вход"
        LOGIN_FAILED = "login_failed", "Неудачная попытка входа"
        LOGIN_THROTTLED = "login_throttled", "Вход заблокирован ограничителем"
        USER_ACTIVITY = "user_activity", "Действие пользователя"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="playlist_bridge_security_events")
    username_snapshot = models.CharField(max_length=254, blank=True)
    event_type = models.CharField(max_length=32, choices=EventType.choices, db_index=True)
    ip_address = models.CharField(max_length=45, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    http_method = models.CharField(max_length=10, blank=True)
    route_name = models.CharField(max_length=100, blank=True, db_index=True)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    request_id = models.UUIDField(null=True, blank=True, db_index=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    object_type = models.CharField(max_length=40, blank=True)
    object_id = models.CharField(max_length=80, blank=True)
    referer_host = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "событие безопасности пользователя"
        verbose_name_plural = "события безопасности пользователей"

    def __str__(self):
        return f"{self.username_snapshot} · {self.get_event_type_display()} · {self.created_at:%Y-%m-%d %H:%M}"



class UserEQPreset(models.Model):
    """A user's private equalizer preset."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="eq_presets")
    name = models.CharField(max_length=40)
    gains = models.JSONField()
    frequencies = models.JSONField()
    qs = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "created_at")
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "user",
                name="unique_user_eq_preset_name_ci",
            ),
        ]

    def __str__(self):
        return f"{self.user.get_username()} · {self.name}"


class UserIPBan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ip_address = models.GenericIPAddressField(db_index=True)
    reason = models.CharField(max_length=240)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='created_ip_bans')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='revoked_ip_bans')

    @property
    def is_active(self):
        from django.utils import timezone
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > timezone.now())


class UserAccountBan(models.Model):
    """Append-only account restriction history."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account_ban_history")
    reason = models.CharField(max_length=240)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_account_bans")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="revoked_account_bans")

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "блокировка учётной записи"
        verbose_name_plural = "история блокировок учётных записей"

    @property
    def is_active(self):
        from django.utils import timezone
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > timezone.now())
