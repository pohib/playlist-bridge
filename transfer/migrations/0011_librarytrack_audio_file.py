from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfer", "0010_librarytrack_source_provider")]

    operations = [
        migrations.AddField(
            model_name="librarytrack",
            name="audio_file",
            field=models.FileField(blank=True, upload_to="user-audio/%Y/%m/"),
        ),
    ]
