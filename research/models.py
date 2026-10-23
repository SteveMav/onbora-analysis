import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ArspImport(models.Model):
    file_name = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64, unique=True)
    schema_version = models.CharField(max_length=32, default="arsp-v1")
    imported_at = models.DateTimeField(auto_now_add=True)
    validation_report = models.JSONField(default=dict)

    class Meta:
        ordering = ["-imported_at"]


class ArspRecord(models.Model):
    arsp_import = models.ForeignKey(ArspImport, on_delete=models.PROTECT, related_name="records")
    dossier_number = models.CharField(max_length=128)
    legal_name = models.CharField(max_length=512)
    raw_data = models.JSONField()
    normalized_data = models.JSONField()
    warnings = models.JSONField(default=list)

    @property
    def display_legal_name(self) -> str:
        from .text_utils import clean_excel_text

        return clean_excel_text(self.legal_name)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["arsp_import", "dossier_number"], name="unique_dossier_per_import"),
        ]


class ResearchRun(models.Model):
    class State(models.TextChoices):
        QUEUED = "queued", "En attente"
        RESEARCHING = "researching", "Recherche en cours"
        AWAITING_REVIEW = "awaiting_review", "À relire"
        REVIEWED = "reviewed", "Relue"
        FAILED = "failed", "Échec"
        CANCELLED = "cancelled", "Annulée"

    class Coverage(models.TextChoices):
        COMPLETE = "complete", "Complète"
        PARTIAL = "partial", "Partielle"

    class IdentityStatus(models.TextChoices):
        CONFIRMED = "confirmed", "confirmée"
        PROBABLE = "probable", "probable"
        AMBIGUOUS = "ambiguous", "ambiguë"
        NOT_FOUND = "not_found", "non trouvée"

    source_record = models.ForeignKey(ArspRecord, on_delete=models.PROTECT, related_name="research_runs")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_research_runs")
    request_fingerprint = models.CharField(max_length=64)
    seed_snapshot = models.JSONField()
    protocol_version = models.CharField(max_length=32, default="research-v3")
    rules_version = models.CharField(max_length=32, default="rules-v1")
    state = models.CharField(max_length=32, choices=State.choices, default=State.QUEUED)
    coverage = models.CharField(max_length=16, choices=Coverage.choices, default=Coverage.COMPLETE)
    limitations = models.JSONField(default=list)
    identity_status = models.CharField(max_length=32, choices=IdentityStatus.choices, blank=True)
    result_summary = models.JSONField(default=dict)
    ai_summary = models.JSONField(default=dict)
    ai_model = models.CharField(max_length=128, blank=True)
    cancellation_requested = models.BooleanField(default=False)
    lease_owner = models.CharField(max_length=128, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    previous_run = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="retries")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["request_fingerprint"],
                condition=Q(state__in=["queued", "researching"]),
                name="unique_active_research_fingerprint",
            )
        ]
        indexes = [models.Index(fields=["state", "created_at"])]


class SerpApiSearch(models.Model):
    class State(models.TextChoices):
        RUNNING = "running", "En cours"
        COMPLETE = "complete", "Terminée"
        FAILED = "failed", "Échec"

    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    submission_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    scenario = models.CharField(max_length=32)
    query = models.CharField(max_length=500)
    engine = models.CharField(max_length=32)
    parameters = models.JSONField(default=dict)
    state = models.CharField(max_length=16, choices=State.choices, default=State.RUNNING)
    report = models.JSONField(default=dict)
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class ResearchBatch(models.Model):
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="research_batches")
    submission_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class ResearchBatchItem(models.Model):
    batch = models.ForeignKey(ResearchBatch, on_delete=models.CASCADE, related_name="items")
    research_run = models.ForeignKey(ResearchRun, on_delete=models.PROTECT, related_name="batch_items")
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "research_run"], name="unique_run_per_batch"),
            models.UniqueConstraint(fields=["batch", "position"], name="unique_position_per_batch"),
            models.CheckConstraint(condition=Q(position__gte=1, position__lte=5), name="batch_position_one_to_five"),
        ]


class ResearchEvent(models.Model):
    research_run = models.ForeignKey(ResearchRun, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=64)
    previous_state = models.CharField(max_length=32, blank=True)
    new_state = models.CharField(max_length=32, blank=True)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class SourceAttempt(models.Model):
    class Status(models.TextChoices):
        RETURNED = "returned", "Retourné"
        FILTERED = "filtered", "Écarté"
        ACCESSIBLE = "accessible", "Accessible"
        UNAVAILABLE = "unavailable", "Indisponible"

    research_run = models.ForeignKey(ResearchRun, on_delete=models.PROTECT, related_name="source_attempts")
    provider = models.CharField(max_length=32, default="searxng")
    query = models.TextField()
    category = models.CharField(max_length=32)
    url = models.URLField(max_length=2048, blank=True)
    title = models.CharField(max_length=1000, blank=True)
    snippet = models.TextField(blank=True)
    search_rank = models.PositiveIntegerField(default=0)
    relevance_score = models.IntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class EvidenceCapture(models.Model):
    class AccessStatus(models.TextChoices):
        ACCESSIBLE = "accessible", "Accessible"
        PARTIAL = "partial", "Partial"
        UNAVAILABLE = "unavailable", "Unavailable"

    canonical_url = models.URLField(max_length=2048)
    observed_url = models.URLField(max_length=2048)
    title = models.CharField(max_length=1000, blank=True)
    publisher = models.CharField(max_length=255, blank=True)
    source_type = models.CharField(max_length=32, default="other")
    relationship = models.CharField(max_length=32, default="discovery_only")
    access_status = models.CharField(max_length=16, choices=AccessStatus.choices)
    content_hash = models.CharField(max_length=64)
    # Kept for compatibility with the first local integration migration. New
    # assessments belong to RunEvidence because relevance is company-specific.
    relevant_excerpt = models.TextField(blank=True, default="")
    relevance_score = models.IntegerField(default=0)
    verdict = models.CharField(max_length=32, blank=True, default="")
    reasons = models.JSONField(default=list)
    collected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["canonical_url", "content_hash"],
                name="unique_evidence_url_content",
            )
        ]


class RunEvidence(models.Model):
    research_run = models.ForeignKey(ResearchRun, on_delete=models.PROTECT, related_name="run_evidence")
    evidence = models.ForeignKey(EvidenceCapture, on_delete=models.PROTECT, related_name="run_links")
    position = models.PositiveIntegerField()
    relevant_excerpt = models.TextField(blank=True, default="")
    relevance_score = models.IntegerField(default=0)
    verdict = models.CharField(max_length=32, default="")
    reasons = models.JSONField(default=list)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["research_run", "evidence"],
                name="unique_evidence_per_run",
            )
        ]


class HumanBenchmark(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "En cours"
        COMPLETED = "completed", "Terminé"

    name = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="human_benchmarks",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class HumanBenchmarkCase(models.Model):
    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "À évaluer"
        COMPLETED = "completed", "Évalué"

    class SourcePotential(models.TextChoices):
        UNKNOWN = "unknown", "Non évalué"
        NONE = "none", "Aucune information utile"
        LIMITED = "limited", "Quelques informations utiles"
        USEFUL = "useful", "Informations réellement utiles"

    class SystemVerdict(models.TextChoices):
        NOT_REVIEWED = "not_reviewed", "Non évalué"
        USEFUL = "useful", "Utile"
        PARTIAL = "partial", "Partiellement utile"
        NOT_USEFUL = "not_useful", "Pas utile"
        WRONG_ENTITY = "wrong_entity", "Mauvaise entreprise"

    class IdentityCheck(models.TextChoices):
        NOT_REVIEWED = "not_reviewed", "Non évaluée"
        CORRECT = "correct", "Correcte"
        UNCERTAIN = "uncertain", "Incertaine"
        INCORRECT = "incorrect", "Incorrecte"

    benchmark = models.ForeignKey(HumanBenchmark, on_delete=models.CASCADE, related_name="cases")
    source_record = models.ForeignKey(ArspRecord, on_delete=models.PROTECT, related_name="benchmark_cases")
    research_run = models.ForeignKey(
        ResearchRun,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="benchmark_cases",
    )
    position = models.PositiveSmallIntegerField()
    review_status = models.CharField(
        max_length=16,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
    )
    source_potential = models.CharField(
        max_length=16,
        choices=SourcePotential.choices,
        default=SourcePotential.UNKNOWN,
    )
    system_verdict = models.CharField(
        max_length=16,
        choices=SystemVerdict.choices,
        default=SystemVerdict.NOT_REVIEWED,
    )
    identity_check = models.CharField(
        max_length=16,
        choices=IdentityCheck.choices,
        default=IdentityCheck.NOT_REVIEWED,
    )
    pages_reviewed = models.PositiveSmallIntegerField(default=0)
    useful_fact_count = models.PositiveSmallIntegerField(default=0)
    human_findings = models.TextField(blank=True)
    missed_information = models.TextField(blank=True)
    reviewer_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_benchmark_cases",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["benchmark", "source_record"], name="unique_record_per_benchmark"),
            models.UniqueConstraint(fields=["benchmark", "position"], name="unique_position_per_benchmark"),
        ]


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=64)
    resource_type = models.CharField(max_length=64)
    resource_id = models.CharField(max_length=64)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
