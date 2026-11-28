import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("transfer", "0017_usersecurityevent_activity_context"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserEQPreset",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=40)),
                ("gains", models.JSONField()),
                ("frequencies", models.JSONField()),
                ("qs", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="eq_presets", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("name", "created_at")},
        ),
        migrations.AddConstraint(
            model_name="usereqpreset",
            constraint=models.UniqueConstraint(Lower("name"), "user", name="unique_user_eq_preset_name_ci"),
        ),
    ]
