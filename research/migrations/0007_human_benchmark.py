from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("research", "0006_gemini_research_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="HumanBenchmark",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("status", models.CharField(choices=[("in_progress", "En cours"), ("completed", "Terminé")], default="in_progress", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="human_benchmarks", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="HumanBenchmarkCase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveSmallIntegerField()),
                ("review_status", models.CharField(choices=[("pending", "À évaluer"), ("completed", "Évalué")], default="pending", max_length=16)),
                ("source_potential", models.CharField(choices=[("unknown", "Non évalué"), ("none", "Aucune information utile"), ("limited", "Quelques informations utiles"), ("useful", "Informations réellement utiles")], default="unknown", max_length=16)),
                ("system_verdict", models.CharField(choices=[("not_reviewed", "Non évalué"), ("useful", "Utile"), ("partial", "Partiellement utile"), ("not_useful", "Pas utile"), ("wrong_entity", "Mauvaise entreprise")], default="not_reviewed", max_length=16)),
                ("identity_check", models.CharField(choices=[("not_reviewed", "Non évaluée"), ("correct", "Correcte"), ("uncertain", "Incertaine"), ("incorrect", "Incorrecte")], default="not_reviewed", max_length=16)),
                ("pages_reviewed", models.PositiveSmallIntegerField(default=0)),
                ("useful_fact_count", models.PositiveSmallIntegerField(default=0)),
                ("human_findings", models.TextField(blank=True)),
                ("missed_information", models.TextField(blank=True)),
                ("reviewer_notes", models.TextField(blank=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("benchmark", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cases", to="research.humanbenchmark")),
                ("research_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="benchmark_cases", to="research.researchrun")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reviewed_benchmark_cases", to=settings.AUTH_USER_MODEL)),
                ("source_record", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="benchmark_cases", to="research.arsprecord")),
            ],
            options={
                "ordering": ["position", "id"],
                "constraints": [
                    models.UniqueConstraint(fields=("benchmark", "source_record"), name="unique_record_per_benchmark"),
                    models.UniqueConstraint(fields=("benchmark", "position"), name="unique_position_per_benchmark"),
                ],
            },
        ),
    ]
