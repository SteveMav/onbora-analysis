"""Claim and execute bounded Onbora research runs."""

from __future__ import annotations

import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from research.models import ResearchEvent, ResearchRun
from research.pipeline import execute_research_run


class Command(BaseCommand):
    help = "Claim and execute one run, or continuously process the local queue."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--worker-id", default="local-worker")
        parser.add_argument("--loop", action="store_true", help="Wait for and process new runs continuously.")
        parser.add_argument("--poll-seconds", type=float, default=2.0)

    def handle(self, *args, **options) -> None:
        while True:
            processed = self._handle_one(options["worker_id"])
            if not options["loop"]:
                if not processed:
                    self.stdout.write("No runnable research run.")
                return
            if not processed:
                time.sleep(max(0.2, min(options["poll_seconds"], 30.0)))

    def _handle_one(self, worker_id: str) -> bool:
        now = timezone.now()
        with transaction.atomic():
            run = (
                ResearchRun.objects.select_for_update()
                .filter(
                    Q(state=ResearchRun.State.QUEUED)
                    | Q(state=ResearchRun.State.RESEARCHING, cancellation_requested=True)
                    | Q(state=ResearchRun.State.RESEARCHING, lease_expires_at__lt=now)
                )
                .order_by("created_at")
                .first()
            )
            if run is None:
                return False
            previous_state = run.state
            if run.cancellation_requested:
                run.state = ResearchRun.State.CANCELLED
                run.completed_at = now
                run.lease_owner = ""
                run.lease_expires_at = None
                event_type = "research_cancelled"
            else:
                run.state = ResearchRun.State.RESEARCHING
                run.started_at = run.started_at or now
                run.lease_owner = worker_id
                run.lease_expires_at = now + timedelta(minutes=10)
                event_type = "research_started" if previous_state == ResearchRun.State.QUEUED else "research_resumed"
            run.save()
            ResearchEvent.objects.create(
                research_run=run,
                event_type=event_type,
                previous_state=previous_state,
                new_state=run.state,
            )
        self.stdout.write(f"Run {run.pk}: {previous_state} -> {run.state}")
        if run.state == ResearchRun.State.CANCELLED:
            return True

        try:
            completed = execute_research_run(run)
        except Exception as error:
            with transaction.atomic():
                failed = ResearchRun.objects.select_for_update().get(pk=run.pk)
                previous_state = failed.state
                failed.state = ResearchRun.State.FAILED
                failed.coverage = ResearchRun.Coverage.PARTIAL
                failed.limitations = ["La collecte n’a pas pu être terminée. Vérifie SearXNG puis relance la recherche."]
                failed.completed_at = timezone.now()
                failed.lease_owner = ""
                failed.lease_expires_at = None
                failed.save()
                ResearchEvent.objects.create(
                    research_run=failed,
                    event_type="research_failed",
                    previous_state=previous_state,
                    new_state=failed.state,
                    details={"error_type": type(error).__name__, "message": str(error)[:500]},
                )
            self.stderr.write(self.style.ERROR(f"Run {run.pk} failed: {type(error).__name__}: {error}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Run {run.pk} -> {completed.state}"))
        return True
