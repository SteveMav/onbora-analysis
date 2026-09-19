from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from research.models import (
    ArspImport,
    ArspRecord,
    AuditEvent,
    HumanBenchmark,
    HumanBenchmarkCase,
    ResearchRun,
)


class HumanBenchmarkTests(TestCase):
    def setUp(self):
        reviewer_group = Group.objects.create(name="reviewer")
        kam_group = Group.objects.create(name="kam")
        self.reviewer = get_user_model().objects.create_user(username="reviewer")
        self.reviewer.groups.add(reviewer_group)
        self.kam = get_user_model().objects.create_user(username="kam-benchmark")
        self.kam.groups.add(kam_group)
        imported = ArspImport.objects.create(file_name="benchmark.xlsx", file_hash="9" * 64)
        self.records = []
        for index in range(12):
            self.records.append(ArspRecord.objects.create(
                arsp_import=imported,
                dossier_number=f"B-{index:02d}",
                legal_name=f"Entreprise Benchmark {index:02d}",
                raw_data={
                    "Dénomination": f"Entreprise Benchmark {index:02d}",
                    "Numéro Dossier": f"B-{index:02d}",
                    "RCCM": f"RCCM-{index:02d}",
                    "Province": "Kinshasa",
                },
                normalized_data={},
            ))

    def test_reviewer_creates_a_ten_company_random_benchmark(self):
        self.client.force_login(self.reviewer)

        response = self.client.post("/benchmarks/create", {
            "name": "Test de septembre",
            "selection_mode": "random",
        })

        self.assertEqual(response.status_code, 302)
        benchmark = HumanBenchmark.objects.get()
        self.assertEqual(benchmark.name, "Test de septembre")
        self.assertEqual(benchmark.cases.count(), 10)
        self.assertEqual(ResearchRun.objects.filter(state=ResearchRun.State.QUEUED).count(), 10)
        self.assertEqual(
            list(benchmark.cases.order_by("position").values_list("position", flat=True)),
            list(range(1, 11)),
        )
        self.assertTrue(AuditEvent.objects.filter(action="human_benchmark_created").exists())

    def test_kam_cannot_access_or_create_benchmarks(self):
        self.client.force_login(self.kam)

        self.assertEqual(self.client.get("/benchmarks/").status_code, 404)
        self.assertEqual(
            self.client.post("/benchmarks/create", {"selection_mode": "random"}).status_code,
            404,
        )
        self.assertFalse(HumanBenchmark.objects.exists())

    def test_recent_mode_reuses_ten_completed_runs(self):
        for index, record in enumerate(self.records[:10]):
            ResearchRun.objects.create(
                source_record=record,
                requested_by=self.reviewer,
                request_fingerprint=f"{index:064x}",
                seed_snapshot={},
                state=ResearchRun.State.AWAITING_REVIEW,
            )
        self.client.force_login(self.reviewer)

        response = self.client.post("/benchmarks/create", {"selection_mode": "recent"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ResearchRun.objects.count(), 10)
        self.assertEqual(HumanBenchmark.objects.get().cases.count(), 10)

    def test_human_evaluation_is_persisted_and_completes_the_case(self):
        benchmark = HumanBenchmark.objects.create(name="Évaluation", created_by=self.reviewer)
        run = ResearchRun.objects.create(
            source_record=self.records[0],
            requested_by=self.reviewer,
            request_fingerprint="a" * 64,
            seed_snapshot={},
            state=ResearchRun.State.AWAITING_REVIEW,
        )
        case = HumanBenchmarkCase.objects.create(
            benchmark=benchmark,
            source_record=self.records[0],
            research_run=run,
            position=1,
        )
        self.client.force_login(self.reviewer)

        response = self.client.post(f"/benchmarks/{benchmark.pk}/cases/{case.pk}", {
            f"case-{case.pk}-source_potential": "useful",
            f"case-{case.pk}-identity_check": "correct",
            f"case-{case.pk}-system_verdict": "partial",
            f"case-{case.pk}-pages_reviewed": "3",
            f"case-{case.pk}-useful_fact_count": "4",
            f"case-{case.pk}-human_findings": "Un nouveau projet est annoncé sur le site officiel.",
            f"case-{case.pk}-missed_information": "Onbora n’a pas extrait le nom du projet.",
            f"case-{case.pk}-reviewer_notes": "L’information était dans un tableau.",
        })

        self.assertEqual(response.status_code, 302)
        case.refresh_from_db()
        benchmark.refresh_from_db()
        self.assertEqual(case.review_status, HumanBenchmarkCase.ReviewStatus.COMPLETED)
        self.assertEqual(case.reviewed_by, self.reviewer)
        self.assertEqual(case.useful_fact_count, 4)
        self.assertEqual(benchmark.status, HumanBenchmark.Status.COMPLETED)
        self.assertTrue(AuditEvent.objects.filter(action="human_benchmark_case_updated").exists())

    def test_useful_sources_require_a_human_finding(self):
        benchmark = HumanBenchmark.objects.create(name="Validation", created_by=self.reviewer)
        case = HumanBenchmarkCase.objects.create(
            benchmark=benchmark,
            source_record=self.records[0],
            position=1,
        )
        self.client.force_login(self.reviewer)

        response = self.client.post(f"/benchmarks/{benchmark.pk}/cases/{case.pk}", {
            f"case-{case.pk}-source_potential": "useful",
            f"case-{case.pk}-identity_check": "correct",
            f"case-{case.pk}-system_verdict": "not_useful",
            f"case-{case.pk}-pages_reviewed": "1",
            f"case-{case.pk}-useful_fact_count": "1",
            f"case-{case.pk}-human_findings": "",
            f"case-{case.pk}-missed_information": "",
            f"case-{case.pk}-reviewer_notes": "",
        })

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Décris au moins une information utile trouvée.", status_code=400)
        case.refresh_from_db()
        self.assertEqual(case.review_status, HumanBenchmarkCase.ReviewStatus.PENDING)
