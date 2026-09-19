"""Domain services for immutable ARSP inputs and research run orchestration."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from .models import ArspRecord, AuditEvent, ResearchEvent, ResearchRun


def frozen_seed(record: ArspRecord) -> dict[str, Any]:
    """Return the contractually stable seed without exposing future edits."""
    raw = record.raw_data
    return {
        "source_record_id": record.dossier_number,
        "input_snapshot": {
            "legal_name": raw.get("Dénomination", ""),
            "trade_name": raw.get("Nom Commercial", ""),
            "rccm": raw.get("RCCM", ""),
            "tax_number": raw.get("Num Impôt", ""),
            "province": raw.get("Province", ""),
            "activity_arsp": raw.get("Activité", ""),
            "address_arsp": raw.get("Adresse", ""),
            "phone_arsp": raw.get("Téléphone", ""),
            "email_arsp": raw.get("Email", ""),
        },
        "input_warnings": record.warnings,
    }


def request_fingerprint(record: ArspRecord, protocol_version: str) -> str:
    payload = {
        "record_id": record.pk,
        "import_hash": record.arsp_import.file_hash,
        "protocol_version": protocol_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_or_get_active_run(
    *, record: ArspRecord, requested_by: get_user_model(), protocol_version: str = "research-v3"
) -> tuple[ResearchRun, bool]:
    """Create a run atomically or retrieve its active equivalent.

    The partial unique constraint is the final guard against concurrent requests.
    """
    fingerprint = request_fingerprint(record, protocol_version)
    try:
        with transaction.atomic():
            previous_run = (
                ResearchRun.objects.filter(source_record=record, request_fingerprint=fingerprint)
                .exclude(state__in=[ResearchRun.State.QUEUED, ResearchRun.State.RESEARCHING])
                .order_by("-created_at")
                .first()
            )
            run = ResearchRun.objects.create(
                source_record=record,
                requested_by=requested_by,
                request_fingerprint=fingerprint,
                seed_snapshot=frozen_seed(record),
                protocol_version=protocol_version,
                previous_run=previous_run,
            )
            ResearchEvent.objects.create(
                research_run=run,
                actor=requested_by,
                event_type="research_requested",
                new_state=ResearchRun.State.QUEUED,
            )
            AuditEvent.objects.create(
                actor=requested_by,
                action="research_requested",
                resource_type="research_run",
                resource_id=str(run.pk),
            )
            return run, True
    except IntegrityError:
        run = ResearchRun.objects.get(
            request_fingerprint=fingerprint,
            state__in=[ResearchRun.State.QUEUED, ResearchRun.State.RESEARCHING],
        )
        return run, False


def request_cancellation(*, run: ResearchRun, actor: get_user_model()) -> ResearchRun:
    """Persist a cancellation signal; the worker owns the terminal transition."""
    with transaction.atomic():
        run = ResearchRun.objects.select_for_update().get(pk=run.pk)
        if run.state not in [ResearchRun.State.QUEUED, ResearchRun.State.RESEARCHING]:
            raise ValueError("invalid_state")
        if not run.cancellation_requested:
            run.cancellation_requested = True
            run.save(update_fields=["cancellation_requested"])
            ResearchEvent.objects.create(
                research_run=run,
                actor=actor,
                event_type="research_cancel_requested",
                previous_state=run.state,
                new_state=run.state,
            )
            AuditEvent.objects.create(
                actor=actor,
                action="research_cancel_requested",
                resource_type="research_run",
                resource_id=str(run.pk),
            )
        return run
