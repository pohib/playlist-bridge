from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfer", "0013_transferjob_dispatch_state")]

    operations = [
        migrations.AddField(
            model_name="transferjob",
            name="checkpoint",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
