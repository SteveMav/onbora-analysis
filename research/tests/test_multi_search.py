import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from research.models import (
    ArspImport, ArspRecord, EvidenceCapture, ResearchBatch, ResearchRun, RunEvidence,
)
from research.services import create_or_get_active_run

CATALOG = Path(__file__).parent / "fixtures" / "orange_catalog.json"


@override_settings(ONBORA_OFFER_CATALOG_PATH=CATALOG)
class MultiSearchTests(TestCase):
    def setUp(self):
        group = Group.objects.create(name="kam")
        self.user = get_user_model().objects.create_user(username="batch-user")
        self.other = get_user_model().objects.create_user(username="other-batch-user")
        self.user.groups.add(group)
        self.other.groups.add(group)
        imported = ArspImport.objects.create(file_name="batch.xlsx", file_hash="5" * 64)
        self.records = [ArspRecord.objects.create(
            arsp_import=imported, dossier_number=f"D-{number}", legal_name=f"Entreprise {number}",
            raw_data={"Dénomination": f"Entreprise {number}", "Province": "Kinshasa"},
            normalized_data={},
        ) for number in range(1, 7)]
        self.client.force_login(self.user)

    def launch(self, records=None, token=None):
        return self.client.post("/multi-search/create", {
            "record_ids": [r.pk for r in (records or self.records[:5])],
            "submission_id": str(token or uuid.uuid4()),
        })

    def test_launches_five_companies_in_selection_order_and_saves_report(self):
        chosen = list(reversed(self.records[:5]))
        response = self.launch(chosen)
        batch = ResearchBatch.objects.get()
        self.assertRedirects(response, f"/multi-search/{batch.pk}/")
        self.assertEqual(
            [item.research_run.source_record_id for item in batch.items.all()], [r.pk for r in chosen],
        )
        self.assertEqual(ResearchRun.objects.filter(state="queued").count(), 5)
        page = self.client.get(response.url)
        self.assertContains(page, "0 / 5")
        self.assertContains(page, "Copier les résumés et liens")

    def test_rejects_empty_six_duplicate_and_unknown_selection_atomically(self):
        for ids in ([], [r.pk for r in self.records], [self.records[0].pk] * 2,
                    [self.records[0].pk, 99999], ["invalid"]):
            with self.subTest(ids=ids):
                response = self.client.post("/multi-search/create", {
                    "record_ids": ids, "submission_id": str(uuid.uuid4()),
                })
                self.assertEqual(response.status_code, 302)
                self.assertEqual(ResearchRun.objects.count(), 0)
                self.assertEqual(ResearchBatch.objects.count(), 0)

    def test_duplicate_submission_reuses_batch_even_after_completion(self):
        token = uuid.uuid4()
        first = self.launch(token=token)
        ResearchRun.objects.update(state="awaiting_review")
        second = self.launch(token=token)
        self.assertEqual(first.url, second.url)
        self.assertEqual(ResearchBatch.objects.count(), 1)
        self.assertEqual(ResearchRun.objects.count(), 5)

    def test_reuses_owners_active_search_but_separates_other_users(self):
        own, _ = create_or_get_active_run(record=self.records[0], requested_by=self.user)
        other, _ = create_or_get_active_run(record=self.records[0], requested_by=self.other)
        self.assertNotEqual(own.pk, other.pk)
        self.launch(records=[self.records[0]])
        self.assertEqual(ResearchBatch.objects.get().items.get().research_run_id, own.pk)
        self.assertEqual(ResearchRun.objects.count(), 2)

    def test_other_kam_cannot_view_report_poll_or_reuse_submission(self):
        token = uuid.uuid4()
        created = self.launch(token=token)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(created.url).status_code, 404)
        self.assertEqual(self.client.get(created.url, {"fragment": "1"}).status_code, 404)
        self.assertEqual(self.launch(token=token).status_code, 404)

    def test_reviewer_can_read_but_cannot_launch(self):
        created = self.launch()
        reviewer = get_user_model().objects.create_user(username="reviewer")
        reviewer.groups.add(Group.objects.create(name="reviewer"))
        self.client.force_login(reviewer)
        self.assertEqual(self.client.get(created.url).status_code, 200)
        self.assertEqual(self.launch().status_code, 404)

    def test_no_partial_batch_when_creation_fails(self):
        real = create_or_get_active_run
        calls = 0
        def create_then_fail(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError("fixture failure")
            return real(**kwargs)
        with patch("research.multi_search.create_or_get_active_run", side_effect=create_then_fail):
            with self.assertRaises(RuntimeError):
                self.launch()
        self.assertEqual(ResearchRun.objects.count(), 0)
        self.assertEqual(ResearchBatch.objects.count(), 0)

    def test_rejects_selection_from_a_previous_import(self):
        ArspImport.objects.create(file_name="new.xlsx", file_hash="6" * 64)
        self.launch()
        self.assertEqual(ResearchBatch.objects.count(), 0)

    def test_paginated_filter_returns_html_and_keeps_selection_page_small(self):
        ArspRecord.objects.bulk_create([
            ArspRecord(arsp_import=self.records[0].arsp_import, dossier_number=f"P-{i}",
                       legal_name=f"Pagination {i:02d}", raw_data={}, normalized_data={})
            for i in range(30)
        ])
        page = self.client.get("/multi-search/", {"q": "Pagination", "page": 2})
        self.assertEqual(len(page.context["page_obj"]), 5)
        fragment = self.client.get("/multi-search/", {"q": "D-1", "fragment": 1})
        self.assertIn("Entreprise 1", fragment.json()["html"])
        self.assertNotIn("Entreprise 2", fragment.json()["html"])

    def test_mixed_report_exposes_sources_offers_missing_summary_and_failure(self):
        created = self.launch()
        runs = list(ResearchRun.objects.order_by("id"))
        evidence = EvidenceCapture.objects.create(
            canonical_url="https://example.com/entreprise-1", observed_url="https://example.com/entreprise-1",
            title="Présentation entreprise 1", publisher="example.com", content_hash="a" * 64,
            access_status="accessible",
        )
        RunEvidence.objects.create(research_run=runs[0], evidence=evidence, position=1,
                                   verdict="Pertinente", relevant_excerpt="Entreprise 1 relie ses sites.")
        runs[0].state = "awaiting_review"
        runs[0].identity_status = "confirmed"
        runs[0].ai_summary = {
            "status": "complete", "overview": {"text": "Entreprise 1 opère plusieurs sites.", "evidence_ids": [evidence.pk]},
            "key_facts": [], "gaps": ["Nombre de sites à confirmer."],
        }
        runs[0].result_summary = {"lead_qualification": {
            "status": "complete", "journeys": [{
                "journey_id": "multisite_network", "title": "Sites", "verdict": "a_explorer",
                "verdict_label": "À explorer", "reason": "Plusieurs sites sont mentionnés.",
                "evidence_ids": [evidence.pk], "signals": [],
                "offers": [{"service_id": "liaison_specialisee_vpn", "name": "Liaison Spécialisée VPN"}],
                "next_question": "Combien de sites relier ?",
            }],
        }}
        runs[0].save()
        runs[1].state = "awaiting_review"
        runs[1].ai_summary = {"status": "not_generated", "message": "Aucune preuve exploitable."}
        runs[1].save()
        runs[2].state = "failed"
        runs[2].limitations = ["SearXNG indisponible."]
        runs[2].save()
        runs[3].state = "researching"
        runs[3].save()
        response = self.client.get(created.url)
        self.assertContains(response, "3 / 5")
        self.assertContains(response, "Entreprise 1 opère plusieurs sites.")
        self.assertContains(response, "https://example.com/entreprise-1")
        self.assertContains(response, "Nombre de sites à confirmer.")
        self.assertContains(response, "Résumé IA indisponible.")
        self.assertContains(response, "SearXNG indisponible.")
        self.assertContains(response, "Liaison Spécialisée VPN")
        self.assertIn("Source : https://example.com/entreprise-1", response.context["report_text"])
        self.assertTrue(self.client.get(created.url, {"fragment": 1}).json()["active"])
        ResearchRun.objects.update(state="awaiting_review")
        self.assertFalse(self.client.get(created.url, {"fragment": 1}).json()["active"])

    def test_uncited_summary_is_not_displayed_as_a_fact(self):
        created = self.launch(records=[self.records[0]])
        run = ResearchRun.objects.get()
        run.state = "awaiting_review"
        run.ai_summary = {"status": "complete", "overview": {"text": "Invented claim", "evidence_ids": [999]}}
        run.save()
        page = self.client.get(created.url)
        self.assertNotContains(page, "Invented claim")
        self.assertContains(page, "sources vérifiables")


class ParallelWorkerTests(SimpleTestCase):
    def test_concurrency_limit_is_validated(self):
        for value in (0, 6):
            with self.assertRaises(CommandError):
                call_command("run_research_worker", concurrency=value)

    def test_five_runs_collect_simultaneously_with_sqlite_and_isolated_failure(self):
        # A file database exercises real lock contention; SQLite's shared in-memory
        # test DB does not implement the production busy timeout.
        probe = textwrap.dedent("""
            import django
            django.setup()
            import io
            import threading
            from datetime import timedelta
            from unittest.mock import patch
            from django.contrib.auth import get_user_model
            from django.core.management import call_command
            from django.db import connections, transaction
            from django.utils import timezone
            from research.models import ArspImport, ArspRecord, ResearchRun, SourceAttempt
            from research.services import create_or_get_active_run
            from research.management.commands.run_research_worker import Command
            call_command("migrate", verbosity=0)
            user = get_user_model().objects.create_user(username="parallel-fixture")
            imported = ArspImport.objects.create(file_name="fixture", file_hash="a"*64)
            for i in range(5):
                record = ArspRecord.objects.create(arsp_import=imported, dossier_number=str(i),
                    legal_name=f"Company {i}", raw_data={"Dénomination":f"Company {i}"}, normalized_data={})
                create_or_get_active_run(record=record, requested_by=user)
            barrier = threading.Barrier(5, timeout=12)
            started = []
            lock = threading.Lock()
            def collect(run):
                with lock:
                    started.append(run.pk)
                barrier.wait()
                if run.pk == 3:
                    raise RuntimeError("single company failure")
                SourceAttempt.objects.create(research_run=run, query="fixture", category="identity",
                    status="returned", url="https://example.com/company")
                with transaction.atomic():
                    current = ResearchRun.objects.get(pk=run.pk)
                    current.state = "awaiting_review"
                    current.completed_at = timezone.now()
                    current.lease_owner = ""
                    current.lease_expires_at = None
                    current.save()
                return current
            with patch("research.management.commands.run_research_worker.execute_research_run", side_effect=collect):
                call_command("run_research_worker", concurrency=5, stdout=io.StringIO(), stderr=io.StringIO())
            assert len(set(started)) == 5, started
            assert ResearchRun.objects.filter(state="awaiting_review").count() == 4
            assert ResearchRun.objects.filter(state="failed").count() == 1
            assert SourceAttempt.objects.count() == 4
            # Two worker dispatchers racing for an expired lease must claim it once.
            expired = ResearchRun.objects.first()
            expired.state = "researching"
            expired.lease_expires_at = timezone.now() - timedelta(seconds=1)
            expired.save()
            claim_barrier = threading.Barrier(2, timeout=8)
            claims = []
            def claim(worker):
                try:
                    claim_barrier.wait()
                    result = Command(stdout=io.StringIO())._claim_run(worker)
                    with lock:
                        claims.append(result.pk if result else None)
                finally:
                    connections.close_all()
            threads = [threading.Thread(target=claim, args=(f"worker-{i}",)) for i in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(12)
            assert len(claims) == 2 and claims.count(expired.pk) == 1, claims
            print("Five simultaneous collectors; four completed; one isolated failure; one lease claim.")
        """)
        with tempfile.TemporaryDirectory(prefix="onbora-parallel-") as directory:
            env = dict(os.environ, DJANGO_SETTINGS_MODULE="config.settings",
                       ONBORA_DATABASE_PATH=str(Path(directory) / "fixture.sqlite3"))
            result = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True,
                                    text=True, timeout=45, cwd=Path(__file__).resolve().parents[2])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
