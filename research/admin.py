from django.contrib import admin

from .models import (
    ArspImport,
    ArspRecord,
    AuditEvent,
    EvidenceCapture,
    HumanBenchmark,
    HumanBenchmarkCase,
    ResearchEvent,
    ResearchRun,
    RunEvidence,
    SourceAttempt,
)

admin.site.register([
    ArspImport,
    ArspRecord,
    ResearchRun,
    ResearchEvent,
    SourceAttempt,
    EvidenceCapture,
    HumanBenchmark,
    HumanBenchmarkCase,
    RunEvidence,
    AuditEvent,
])
