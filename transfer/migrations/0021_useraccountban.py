import django.conf
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(django.conf.settings.AUTH_USER_MODEL),
        ("transfer", "0020_allow_ip_ban_history"),
    ]
    operations = [
        migrations.CreateModel(
            name="UserAccountBan",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("reason", models.CharField(max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(null=True, blank=True, db_index=True)),
                ("revoked_at", models.DateTimeField(null=True, blank=True)),
                ("created_by", models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_account_bans", to=django.conf.settings.AUTH_USER_MODEL)),
                ("revoked_by", models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name="revoked_account_bans", to=django.conf.settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="account_ban_history", to=django.conf.settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "блокировка учётной записи", "verbose_name_plural": "история блокировок учётных записей", "ordering": ("-created_at",)},
        ),
    ]
