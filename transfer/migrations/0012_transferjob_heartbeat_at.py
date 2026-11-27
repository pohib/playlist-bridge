from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfer", "0011_librarytrack_audio_file")]

    operations = [
        migrations.AddField(
            model_name="transferjob",
            name="heartbeat_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
