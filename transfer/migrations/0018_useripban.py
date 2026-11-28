import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('transfer', '0017_usersecurityevent_activity_context'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name='UserIPBan', fields=[('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)), ('ip_address', models.GenericIPAddressField(db_index=True, unique=True)), ('reason', models.CharField(max_length=240)), ('created_at', models.DateTimeField(auto_now_add=True)), ('expires_at', models.DateTimeField(blank=True, db_index=True, null=True)), ('revoked_at', models.DateTimeField(blank=True, null=True)), ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_ip_bans', to=settings.AUTH_USER_MODEL)), ('revoked_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='revoked_ip_bans', to=settings.AUTH_USER_MODEL))])]
