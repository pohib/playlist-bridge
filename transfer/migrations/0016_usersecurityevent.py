import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("transfer", "0015_adminauditevent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserSecurityEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("username_snapshot", models.CharField(blank=True, max_length=254)),
                ("event_type", models.CharField(choices=[
                    ("login_succeeded", "Успешный вход"),
                    ("login_failed", "Неудачная попытка входа"),
                    ("login_throttled", "Вход заблокирован ограничителем"),
                ], db_index=True, max_length=32)),
                ("ip_address", models.CharField(blank=True, max_length=45)),
                ("user_agent", models.CharField(blank=True, max_length=512)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="playlist_bridge_security_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "событие безопасности пользователя",
                "verbose_name_plural": "события безопасности пользователей",
                "ordering": ("-created_at",),
            },
        ),
    ]
