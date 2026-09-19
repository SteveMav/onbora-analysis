from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("research", "0005_alter_researchrun_protocol_version"),
    ]

    operations = [
        migrations.AlterField(
            model_name="researchrun",
            name="protocol_version",
            field=models.CharField(default="research-v3", max_length=32),
        ),
        migrations.AddField(
            model_name="researchrun",
            name="ai_model",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="researchrun",
            name="ai_summary",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="sourceattempt",
            name="provider",
            field=models.CharField(default="searxng", max_length=32),
        ),
    ]
