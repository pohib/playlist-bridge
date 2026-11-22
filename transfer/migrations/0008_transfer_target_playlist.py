import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfer", "0007_library_transfer_review")]

    operations = [
        migrations.AddField(
            model_name="librarytransfer",
            name="target_playlist",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="source_transfers",
                to="transfer.libraryplaylist",
            ),
        ),
    ]
