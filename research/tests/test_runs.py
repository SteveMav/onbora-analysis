from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from unittest.mock import patch

from research.models import ArspImport, ArspRecord, ResearchEvent, ResearchRun, SourceAttempt


class ResearchRunApiTests(TestCase):
    def setUp(self):
        self.kam_group = Group.objects.create(name="kam")
        self.operator_group = Group.objects.create(name="operator")
        self.kam = get_user_model().objects.create_user(username="kam")
        self.kam.groups.add(self.kam_group)
        self.other_kam = get_user_model().objects.create_user(username="other")
        self.other_kam.groups.add(self.kam_group)
        self.operator = get_user_model().objects.create_user(username="operator")
        self.operator.groups.add(self.operator_group)
        imported = ArspImport.objects.create(file_name="fixture.xlsx", file_hash="a" * 64)
        self.record = ArspRecord.objects.create(
            arsp_import=imported,
            dossier_number="D-1",
            legal_name="Société Exemple",
            raw_data={"Dénomination": "Société Exemple", "Numéro Dossier": "D-1"},
            normalized_data={"Dénomination": "société exemple", "Numéro Dossier": "d-1"},
        )

    def test_kam_creates_and_reuses_an_active_run(self):
        self.client.force_login(self.kam)
        response = self.client.post("/api/v1/research-runs", data={"source_record_id": self.record.pk}, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        second = self.client.post("/api/v1/research-runs", data={"source_record_id": self.record.pk}, content_type="application/json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(response.json()["run_id"], second.json()["run_id"])
        self.assertEqual(ResearchRun.objects.count(), 1)
        self.assertEqual(ResearchEvent.objects.filter(event_type="research_requested").count(), 1)

    def test_kam_cannot_discover_another_kams_run(self):
        run = ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.kam,
            request_fingerprint="b" * 64,
            seed_snapshot={},
        )
        self.client.force_login(self.other_kam)
        response = self.client.get(f"/api/v1/research-runs/{run.pk}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "not_found_or_forbidden")

    def test_only_operator_can_request_cancellation(self):
        run = ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.kam,
            request_fingerprint="c" * 64,
            seed_snapshot={},
        )
        self.client.force_login(self.kam)
        denied = self.client.post(f"/api/v1/research-runs/{run.pk}/cancel")
        self.assertEqual(denied.status_code, 404)

        self.client.force_login(self.operator)
        accepted = self.client.post(f"/api/v1/research-runs/{run.pk}/cancel")
        self.assertEqual(accepted.status_code, 202)
        run.refresh_from_db()
        self.assertTrue(run.cancellation_requested)

    def test_worker_confirms_cancellation_without_starting_collection(self):
        run = ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.kam,
            request_fingerprint="d" * 64,
            seed_snapshot={},
            cancellation_requested=True,
        )
        call_command("run_research_worker")
        run.refresh_from_db()
        self.assertEqual(run.state, ResearchRun.State.CANCELLED)

    @patch("research.management.commands.run_research_worker.execute_research_run")
    def test_worker_claims_queued_run_even_when_another_run_is_researching(self, execute):
        ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.kam,
            request_fingerprint="e" * 64,
            seed_snapshot={},
            state=ResearchRun.State.RESEARCHING,
        )
        queued = ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.kam,
            request_fingerprint="f" * 64,
            seed_snapshot={},
        )
        call_command("run_research_worker", worker_id="worker-a")
        queued.refresh_from_db()
        self.assertEqual(queued.state, ResearchRun.State.RESEARCHING)
        self.assertEqual(queued.lease_owner, "worker-a")
        execute.assert_called_once()

    def test_a_failed_run_can_be_relaunched_as_a_new_run(self):
        ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.kam,
            request_fingerprint="g" * 64,
            seed_snapshot={},
            state=ResearchRun.State.FAILED,
        )
        self.client.force_login(self.kam)
        response = self.client.post("/api/v1/research-runs", data={"source_record_id": self.record.pk}, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ResearchRun.objects.filter(state=ResearchRun.State.QUEUED).count(), 1)

    def test_run_api_exposes_every_discovered_source_with_its_url(self):
        run = ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.kam,
            request_fingerprint="h" * 64,
            seed_snapshot={},
            state=ResearchRun.State.AWAITING_REVIEW,
        )
        SourceAttempt.objects.create(
            research_run=run,
            query='"Société Exemple"',
            category="identity",
            url="https://example.com/company",
            title="Site de la société",
            snippet="Présentation publique",
            relevance_score=8,
            status=SourceAttempt.Status.RETURNED,
        )
        self.client.force_login(self.kam)

        response = self.client.get(f"/api/v1/research-runs/{run.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sources"][0]["url"], "https://example.com/company")
        self.assertEqual(response.json()["sources"][0]["provider"], "searxng")
        self.assertIn("ai_summary", response.json())
