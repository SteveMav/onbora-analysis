from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from research.gemini import GeminiServiceError
from research.models import ArspImport, ArspRecord, EvidenceCapture, ResearchRun, RunEvidence, SourceAttempt
from research.pipeline import execute_research_run
from research.web_research import (
    CompanySeed,
    PageAssessment,
    QuerySpec,
    SearchHit,
    SearxngClient,
    assess_text,
    build_lead_query_plan,
    build_query_plan,
    canonicalize_url,
    company_from_snapshot,
    company_website_domain,
    is_seed_website,
    rank_search_hit,
    source_classification,
    validate_public_url,
)


CATALOG_FIXTURE = Path(__file__).parent / "fixtures" / "orange_catalog.json"


class QueryPlanningTests(TestCase):
    def test_builds_focused_queries_and_ranks_identity_matches_first(self):
        company = CompanySeed(
            legal_name="Entreprise Test Congo",
            sector="Transport et logistique",
            province="Kinshasa",
            rccm="CD/KIN/RCCM/24-B-001",
        )

        plan = build_query_plan(company)
        good = rank_search_hit(
            "Entreprise Test Congo à Kinshasa",
            "Transport et logistique — RCCM CD/KIN/RCCM/24-B-001",
            "https://entreprise-test.example/",
            company,
        )
        noise = rank_search_hit(
            "Calendrier du championnat",
            "Actualités sportives internationales",
            "https://sports.example/article",
            company,
        )

        self.assertEqual(plan[0].category, "registry")
        self.assertGreaterEqual(len(plan), 3)
        self.assertTrue({
            "registry", "registry_name", "arsp", "identity", "sector",
        }.issubset({item.category for item in plan}))
        self.assertFalse(any(item.category.startswith("lead_") for item in plan))
        self.assertTrue({
            "lead_network", "lead_customer", "lead_mobility", "lead_collaboration",
            "lead_cloud",
        }.issubset({item.category for item in build_lead_query_plan(company)}))
        self.assertNotIn("lead_security", {item.category for item in plan})
        self.assertGreater(good, noise)
        self.assertLess(noise, 0)

    def test_canonicalizes_tracking_links_and_rejects_private_targets(self):
        self.assertEqual(
            canonicalize_url("https://Example.com/page?utm_source=test&item=2#section"),
            "https://example.com/page?item=2",
        )
        with self.assertRaisesRegex(ValueError, "locale ou privée"):
            validate_public_url("http://127.0.0.1/private")

    def test_removes_excel_control_escapes_and_adds_a_brand_query(self):
        company = company_from_snapshot({"input_snapshot": {
            "legal_name": "1FLUENCE SARLU_x000d_",
            "rccm": "CD/KNG/RCCM/17-B-0135_x000d_",
            "province": "Kinshasa",
        }})

        queries = [spec.query for spec in build_query_plan(company)]

        self.assertEqual(company.legal_name, "1FLUENCE SARLU")
        self.assertEqual(company.rccm, "CD/KNG/RCCM/17-B-0135")
        self.assertTrue(all("_x000d_" not in query.casefold() for query in queries))
        self.assertIn('"1FLUENCE"', queries)

    def test_page_title_and_distant_identifier_cannot_confirm_a_homonym(self):
        company = CompanySeed(legal_name="Atlas Kivu SARLU", rccm="CD/GOM/RCCM/26-B-001")
        page = "Atlas Kivu SARLU vend des fournitures.\nAutre Entreprise SARLU | CD/GOM/RCCM/26-B-001"
        assessment = assess_text(company, "Atlas Kivu SARLU : résultat", page, "https://example.org/list")
        self.assertEqual(assessment.verdict, "À vérifier")
        self.assertNotIn("RCCM exact trouvé", assessment.reasons)

        wrong_page = assess_text(company, "Atlas Kivu SARLU : résultat", "Autre Entreprise SARLU est à Goma.", "https://example.org/other")
        self.assertEqual(wrong_page.verdict, "Hors sujet probable")

    def test_name_and_rccm_in_same_passage_are_admitted(self):
        company = CompanySeed(legal_name="Atlas Kivu SARLU", rccm="CD/GOM/RCCM/26-B-001")
        assessment = assess_text(company, "Registre", "Atlas Kivu SARLU | CD/GOM/RCCM/26-B-001 | Transport", "https://arsp.cd/register")
        self.assertEqual(assessment.verdict, "Pertinente")
        self.assertIn("CD/GOM/RCCM/26-B-001", assessment.excerpt)

    def test_name_like_domain_is_not_labeled_as_official_without_proof(self):
        source_type, relationship = source_classification(
            "https://atlas-kivu-news.example/story", CompanySeed(legal_name="Atlas Kivu SARLU")
        )
        self.assertEqual((source_type, relationship), ("other", "discovery_only"))

    def test_brand_without_legal_suffix_is_retained_without_confirming_identity(self):
        company = CompanySeed(legal_name="1FLUENCE SARLU", province="Kinshasa")
        result = assess_text(company, "Source", "#1FLUENCE est une agence de communication à Kinshasa.",
                             "https://directory.example/1fluence")
        self.assertEqual(result.verdict, "À vérifier")
        self.assertIn("agence de communication", result.excerpt)

    def test_brand_matching_uses_word_boundaries(self):
        company = CompanySeed(legal_name="1FLUENCE SARLU")
        result = assess_text(company, "Source", "21FLUENCE propose des services.", "https://example.org")
        self.assertEqual(result.verdict, "Hors sujet probable")

    def test_registry_email_domain_requires_company_specific_match(self):
        company = CompanySeed(legal_name="1FLUENCE SARLU", email="contact@1fluence.net")
        self.assertEqual(company_website_domain(company), "1fluence.net")
        self.assertTrue(is_seed_website("https://www.1fluence.net/", company))
        self.assertFalse(is_seed_website("https://1fluence.net.evil.example/", company))
        for email in ("contact@gmail.com", "contact@example.org", "bad@@1fluence.net"):
            self.assertEqual(company_website_domain(CompanySeed(legal_name="1FLUENCE SARLU", email=email)), "")


class _JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return json.dumps(self.payload).encode()


class SearxngDiagnosticsTests(TestCase):
    @patch("urllib.request.urlopen")
    def test_exposes_unresponsive_engine_diagnostics(self, urlopen):
        urlopen.return_value = _JsonResponse({
            "results": [],
            "unresponsive_engines": [["duckduckgo", "CAPTCHA"]],
        })
        client = SearxngClient()

        client.search(QuerySpec("identity", '"Entreprise Test"'))

        self.assertEqual(client.last_warnings, (("duckduckgo", "CAPTCHA"),))


class _FakeSearchClient:
    def search(self, spec):
        return [
            SearchHit(
                query=spec.query,
                category=spec.category,
                rank=1,
                title="Entreprise Test Congo — fiche officielle",
                url="https://entreprise-test.example/profil#presentation",
                snippet="RCCM CD/KIN/RCCM/24-B-001, transport à Kinshasa",
                discovery_score=0,
            ),
            SearchHit(
                query=spec.query,
                category=spec.category,
                rank=2,
                title="Résultats sportifs",
                url="https://sports.example/match",
                snippet="Calendrier et classement",
                discovery_score=0,
            ),
        ]


class _FakePageFetcher:
    def analyze(self, hit, company):
        return PageAssessment(
            verdict="Pertinente",
            score=10,
            source_type="official",
            relationship="first_party",
            reasons=("nom légal trouvé", "RCCM exact trouvé"),
            excerpt="Entreprise Test Congo, RCCM CD/KIN/RCCM/24-B-001, exploite une flotte de véhicules logistiques.",
            final_url="https://entreprise-test.example/profil",
            content_hash="d" * 64,
        )


class _InitiallyIrrelevantPageFetcher(_FakePageFetcher):
    def analyze(self, hit, company):
        if hit.provider == "gemini":
            assessment = super().analyze(hit, company)
            return PageAssessment(**{**assessment.__dict__, "final_url": hit.url})
        return PageAssessment(
            verdict="Hors sujet probable",
            score=0,
            source_type="other",
            relationship="independent",
            reasons=("pas assez d’éléments pour relier la page à l’entreprise",),
            excerpt="Une autre entreprise.",
            final_url=hit.url,
            content_hash="e" * 64,
        )


class _UnavailableSearchClient:
    def search(self, spec):
        raise RuntimeError("offline")


class _FakeAiClient:
    model = "gemini-test-fast"

    def search(self, company, reason):
        return [SearchHit(
            query=f"Complément Gemini pour {company.legal_name}",
            category="ai_fallback",
            rank=1,
            title="Entreprise Test Congo — registre public",
            url="https://entreprise-test.example/profil",
            snippet="RCCM CD/KIN/RCCM/24-B-001",
            discovery_score=0,
            provider="gemini",
        )]

    def summarize(self, company, evidence):
        items = list(evidence)
        if not items:
            return {"status": "not_generated", "model": self.model, "message": "Aucune preuve exploitable."}
        return {
            "status": "complete",
            "model": self.model,
            "overview": {
                "text": "L’entreprise est reliée au RCCM fourni.",
                "evidence_ids": [items[0].evidence_id],
            },
            "key_facts": [],
            "contradictions": [],
            "gaps": ["Activité récente non confirmée"],
        }


class _WarningSearchClient(_FakeSearchClient):
    last_warnings = (("google", "CAPTCHA"),)


class _SearchFailingAiClient(_FakeAiClient):
    def search(self, company, reason):
        raise GeminiServiceError("Recherche complémentaire Gemini : quota Gemini indisponible ou épuisé.")


class _NewSourceAiClient(_FakeAiClient):
    def search(self, company, reason):
        hit = super().search(company, reason)[0]
        return [SearchHit(**{**hit.__dict__, "url": "https://new-source.example/company"})]


@override_settings(
    ONBORA_ANALYSIS_LIMIT=5,
    ONBORA_GEMINI_ENABLED=False,
    ONBORA_OPENAI_ENABLED=False,
    ONBORA_OFFER_CATALOG_PATH=CATALOG_FIXTURE,
)
class ResearchPipelineTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="kam")
        imported = ArspImport.objects.create(file_name="fixture.xlsx", file_hash="a" * 64)
        self.record = ArspRecord.objects.create(
            arsp_import=imported,
            dossier_number="d-1",
            legal_name="Entreprise Test Congo",
            raw_data={
                "Dénomination": "Entreprise Test Congo",
                "RCCM": "CD/KIN/RCCM/24-B-001",
                "Numéro Dossier": "D-1",
                "Activité": "Transport et logistique",
                "Province": "Kinshasa",
            },
            normalized_data={},
        )
        self.run = ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.user,
            request_fingerprint="b" * 64,
            seed_snapshot={
                "input_snapshot": {
                    "legal_name": "Entreprise Test Congo",
                    "rccm": "CD/KIN/RCCM/24-B-001",
                    "activity_arsp": "Transport et logistique",
                    "province": "Kinshasa",
                }
            },
            state=ResearchRun.State.RESEARCHING,
        )

    def test_deduplicates_results_filters_noise_and_persists_evidence(self):
        completed = execute_research_run(
            self.run,
            search_client=_FakeSearchClient(),
            page_fetcher=_FakePageFetcher(),
        )

        self.assertEqual(completed.state, ResearchRun.State.AWAITING_REVIEW)
        self.assertEqual(completed.identity_status, "confirmed")
        self.assertEqual(completed.result_summary["unique_count"], 2)
        self.assertEqual(completed.result_summary["captured_count"], 1)
        self.assertEqual(RunEvidence.objects.count(), 1)
        self.assertEqual(RunEvidence.objects.get().verdict, "Pertinente")
        self.assertTrue(SourceAttempt.objects.filter(status=SourceAttempt.Status.FILTERED).exists())
        qualification = completed.result_summary["lead_qualification"]
        mobility = next(item for item in qualification["journeys"] if item["journey_id"] == "mobility_m2m")
        self.assertEqual(qualification["status"], "complete")
        self.assertEqual(mobility["verdict"], "a_explorer")
        segmentation = completed.result_summary["sector_segmentation"]
        self.assertEqual(segmentation["status"], "complete")
        self.assertEqual(segmentation["primary"]["segment_id"], "transport_logistics")
        self.assertEqual(segmentation["primary"]["confidence"], "élevée")

    def test_reports_partial_coverage_when_the_search_provider_is_unavailable(self):
        completed = execute_research_run(
            self.run,
            search_client=_UnavailableSearchClient(),
            page_fetcher=_FakePageFetcher(),
        )

        self.assertEqual(completed.state, ResearchRun.State.AWAITING_REVIEW)
        self.assertEqual(completed.coverage, ResearchRun.Coverage.PARTIAL)
        self.assertEqual(completed.identity_status, "not_found")
        self.assertTrue(completed.limitations)
        self.assertFalse(RunEvidence.objects.exists())

    def test_uses_gemini_as_fallback_and_persists_a_sourced_summary(self):
        completed = execute_research_run(
            self.run,
            search_client=_UnavailableSearchClient(),
            page_fetcher=_FakePageFetcher(),
            ai_client=_FakeAiClient(),
        )

        self.assertTrue(completed.result_summary["ai_search_attempted"])
        self.assertEqual(completed.result_summary["ai_search_source_count"], 1)
        self.assertEqual(completed.ai_summary["status"], "complete")
        self.assertEqual(completed.ai_model, "gemini-test-fast")
        self.assertTrue(SourceAttempt.objects.filter(provider="gemini", status="returned").exists())

    def test_skips_gemini_search_when_a_searx_page_is_relevant(self):
        completed = execute_research_run(
            self.run,
            search_client=_WarningSearchClient(),
            page_fetcher=_FakePageFetcher(),
            ai_client=_SearchFailingAiClient(),
        )

        self.assertEqual(completed.state, ResearchRun.State.AWAITING_REVIEW)
        self.assertEqual(completed.ai_summary["status"], "complete")
        self.assertFalse(completed.result_summary["ai_search_attempted"])
        self.assertTrue(SourceAttempt.objects.filter(provider="searxng", status="returned").exists())

    def test_searches_with_gemini_after_promising_searx_links_prove_irrelevant(self):
        completed = execute_research_run(
            self.run,
            search_client=_FakeSearchClient(),
            page_fetcher=_InitiallyIrrelevantPageFetcher(),
            ai_client=_NewSourceAiClient(),
        )

        self.assertTrue(completed.result_summary["ai_search_attempted"])
        self.assertEqual(completed.ai_summary["status"], "complete")
        self.assertEqual(completed.result_summary["captured_count"], 2)
        self.assertTrue(RunEvidence.objects.filter(verdict="Pertinente").exists())
        self.assertTrue(SourceAttempt.objects.filter(provider="gemini", status="accessible").exists())

    def test_keeps_original_evidence_when_gemini_quota_fails_after_irrelevant_pages(self):
        completed = execute_research_run(
            self.run,
            search_client=_FakeSearchClient(),
            page_fetcher=_InitiallyIrrelevantPageFetcher(),
            ai_client=_SearchFailingAiClient(),
        )

        self.assertEqual(completed.state, ResearchRun.State.AWAITING_REVIEW)
        self.assertTrue(any("quota Gemini" in item for item in completed.limitations))
        self.assertTrue(SourceAttempt.objects.filter(provider="searxng", status="returned").exists())


@override_settings(ONBORA_OFFER_CATALOG_PATH=CATALOG_FIXTURE)
class DashboardTests(TestCase):
    def setUp(self):
        group = Group.objects.create(name="kam")
        self.user = get_user_model().objects.create_user(username="kam", password="secret")
        self.user.groups.add(group)
        imported = ArspImport.objects.create(file_name="fixture.xlsx", file_hash="c" * 64)
        self.record = ArspRecord.objects.create(
            arsp_import=imported,
            dossier_number="d-2",
            legal_name="Alpha Services",
            raw_data={"Dénomination": "Alpha Services", "Numéro Dossier": "D-2"},
            normalized_data={},
        )
        self.client.force_login(self.user)

    def test_searches_arsp_and_creates_a_run_from_the_web_ui(self):
        dashboard = self.client.get("/", {"q": "Alpha"})
        self.assertContains(dashboard, "Alpha Services")

        created = self.client.post("/runs/create", {"record_id": self.record.pk})

        run = ResearchRun.objects.get()
        self.assertRedirects(created, f"/runs/{run.pk}/")
        self.assertEqual(run.state, ResearchRun.State.QUEUED)

    def test_company_selector_shows_one_hundred_records_per_page(self):
        ArspRecord.objects.bulk_create([
            ArspRecord(
                arsp_import=self.record.arsp_import,
                dossier_number=f"page-{number}",
                legal_name=f"Entreprise Pagination {number:03d}",
                raw_data={"Dénomination": f"Entreprise Pagination {number:03d}"},
                normalized_data={},
            )
            for number in range(1, 102)
        ])

        response = self.client.get("/", {"q": "Entreprise Pagination", "page": "2"})

        page_obj = response.context["page_obj"]
        self.assertEqual(page_obj.paginator.count, 101)
        self.assertEqual(page_obj.number, 2)
        self.assertEqual(len(response.context["records"]), 1)
        self.assertContains(response, "101 résultats")
        self.assertContains(response, "100 par page")
        self.assertContains(response, "Page 2 sur 2")
        self.assertContains(response, "Précédente")

    def test_run_page_lists_every_discovered_source_as_a_clickable_link(self):
        run = ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.user,
            request_fingerprint="e" * 64,
            seed_snapshot={"input_snapshot": {"legal_name": "Alpha Services"}},
            state=ResearchRun.State.AWAITING_REVIEW,
        )
        SourceAttempt.objects.create(
            research_run=run,
            query='"Alpha Services"',
            category="identity",
            url="https://alpha.example/source",
            title="Une source non analysée",
            snippet="Résultat brut du moteur",
            relevance_score=1,
            status=SourceAttempt.Status.RETURNED,
        )

        response = self.client.get(f"/runs/{run.pk}/")

        self.assertContains(response, "Toutes les sources trouvées")
        self.assertContains(response, 'href="https://alpha.example/source"')
        self.assertContains(response, "Une source non analysée")

    def test_run_page_keeps_sources_visible_beside_the_sourced_ai_summary(self):
        run = ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.user,
            request_fingerprint="f" * 64,
            seed_snapshot={"input_snapshot": {"legal_name": "Alpha Services"}},
            state=ResearchRun.State.AWAITING_REVIEW,
            ai_model="gemini-test-fast",
        )
        evidence = EvidenceCapture.objects.create(
            canonical_url="https://alpha.example/about",
            observed_url="https://alpha.example/about",
            title="Présentation Alpha",
            publisher="alpha.example",
            access_status=EvidenceCapture.AccessStatus.ACCESSIBLE,
            content_hash="9" * 64,
        )
        link = RunEvidence.objects.create(
            research_run=run,
            evidence=evidence,
            position=1,
            relevant_excerpt="Alpha Services opère à Kinshasa.",
            relevance_score=8,
            verdict="Pertinente",
        )
        run.ai_summary = {
            "status": "complete",
            "model": "gemini-test-fast",
            "overview": {"text": "Alpha Services opère à Kinshasa.", "evidence_ids": [link.evidence_id]},
            "key_facts": [],
            "contradictions": [],
            "gaps": [],
        }
        run.save(update_fields=["ai_summary"])

        response = self.client.get(f"/runs/{run.pk}/")

        self.assertContains(response, "Résumé IA sourcé")
        self.assertContains(response, "Alpha Services opère à Kinshasa.")
        self.assertContains(response, 'href="https://alpha.example/about"')
        self.assertContains(response, "Toutes les sources trouvées")

    def test_run_page_displays_a_sourced_sector_segmentation(self):
        run = ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.user,
            request_fingerprint="2" * 64,
            seed_snapshot={"input_snapshot": {
                "legal_name": "Alpha Services",
                "activity_arsp": "Transport et logistique",
            }},
            state=ResearchRun.State.AWAITING_REVIEW,
        )
        evidence = EvidenceCapture.objects.create(
            canonical_url="https://alpha.example/transport",
            observed_url="https://alpha.example/transport",
            title="Activités logistiques Alpha",
            publisher="alpha.example",
            access_status=EvidenceCapture.AccessStatus.ACCESSIBLE,
            content_hash="8" * 64,
        )
        link = RunEvidence.objects.create(
            research_run=run,
            evidence=evidence,
            position=1,
            relevant_excerpt="Alpha Services assure le transport et la logistique.",
            relevance_score=8,
            verdict="Pertinente",
        )
        run.result_summary = {
            "sector_segmentation": {
                "status": "complete",
                "taxonomy_version": "onbora-sector-v1",
                "raw_activity": "Transport et logistique",
                "primary": {
                    "segment_id": "transport_logistics",
                    "label": "Transport et logistique",
                    "confidence": "élevée",
                    "reason": "L’activité ARSP est corroborée par une source publique.",
                    "evidence_ids": [link.evidence_id],
                },
                "alternatives": [],
            }
        }
        run.save(update_fields=["result_summary"])

        response = self.client.get(f"/runs/{run.pk}/")

        self.assertContains(response, "Secteur d’activité")
        self.assertContains(response, "Transport et logistique")
        self.assertContains(response, "confiance élevée")
        self.assertContains(response, 'href="https://alpha.example/transport"')

    def test_run_page_displays_only_rdc_orange_lead_journeys(self):
        run = ResearchRun.objects.create(
            source_record=self.record,
            requested_by=self.user,
            request_fingerprint="1" * 64,
            seed_snapshot={"input_snapshot": {"legal_name": "Alpha Services"}},
            state=ResearchRun.State.AWAITING_REVIEW,
            result_summary={
                "lead_qualification": {
                    "status": "complete",
                    "catalog_version": "orange-test-v1",
                    "journeys": [
                        {
                            "journey_id": "multisite_network",
                            "title": "Réseau multi-sites",
                            "description": "Relier plusieurs sites.",
                            "verdict": "a_explorer",
                            "verdict_label": "À explorer",
                            "confidence": "faible",
                            "reason": "Un signal reste à confirmer.",
                            "signals": [],
                            "evidence_ids": [],
                            "sector_fit": False,
                            "offers": [{"service_id": "liaison_specialisee_vpn", "name": "Liaison Spécialisée VPN"}],
                            "missing_information": "Nombre de sites.",
                            "next_question": "Combien de sites faut-il relier ?",
                            "next_action": "Confirmer les sites.",
                        },
                        {
                            "journey_id": "payments_customer_communication",
                            "title": "Paiement et communication client",
                            "description": "Paiement et messages.",
                            "verdict": "non_qualifiable",
                            "verdict_label": "Non qualifiable",
                            "confidence": "faible",
                            "reason": "Aucun signal.",
                            "signals": [],
                            "evidence_ids": [],
                            "sector_fit": False,
                            "offers": [],
                            "missing_information": "Parcours client.",
                            "next_question": "Comment encaissez-vous ?",
                            "next_action": "Qualifier le parcours.",
                        },
                        {
                            "journey_id": "mobility_m2m",
                            "title": "Mobilité et M2M",
                            "description": "Équipes et équipements.",
                            "verdict": "non_qualifiable",
                            "verdict_label": "Non qualifiable",
                            "confidence": "faible",
                            "reason": "Aucun signal.",
                            "signals": [],
                            "evidence_ids": [],
                            "sector_fit": False,
                            "offers": [],
                            "missing_information": "Taille de la flotte.",
                            "next_question": "Combien de véhicules ?",
                            "next_action": "Qualifier la flotte.",
                        },
                        {
                            "journey_id": "collaboration_productivity",
                            "title": "Collaboration et productivité",
                            "description": "Messagerie et collaboration.",
                            "verdict": "non_qualifiable",
                            "verdict_label": "Non qualifiable",
                            "confidence": "faible",
                            "reason": "Aucun signal.",
                            "signals": [],
                            "evidence_ids": [],
                            "sector_fit": False,
                            "offers": [],
                            "missing_information": "Nombre d’utilisateurs.",
                            "next_question": "Quels outils utilisez-vous ?",
                            "next_action": "Qualifier les usages.",
                        },
                        {
                            "journey_id": "cybersecurity",
                            "title": "Cybersécurité",
                            "description": "Sécurité des systèmes.",
                            "verdict": "non_qualifiable",
                            "verdict_label": "Non qualifiable",
                            "confidence": "faible",
                            "reason": "Aucun signal.",
                            "signals": [],
                            "evidence_ids": [],
                            "sector_fit": False,
                            "offers": [],
                            "missing_information": "Périmètre critique.",
                            "next_question": "Quels systèmes sont critiques ?",
                            "next_action": "Qualifier le périmètre.",
                        },
                        {
                            "journey_id": "cloud_datacenter_continuity",
                            "title": "Datacenter et continuité",
                            "description": "Hébergement et reprise.",
                            "verdict": "non_qualifiable",
                            "verdict_label": "Non qualifiable",
                            "confidence": "faible",
                            "reason": "Aucun signal.",
                            "signals": [],
                            "evidence_ids": [],
                            "sector_fit": False,
                            "offers": [
                                {"service_id": "hebergement_datacenter", "name": "Hébergement Datacenter"},
                                {"service_id": "global_cloud_portfolio", "name": "Cloud international Orange Business"},
                            ],
                            "missing_information": "Hébergement actuel.",
                            "next_question": "Où sont les applications ?",
                            "next_action": "Qualifier l’hébergement.",
                        },
                    ],
                }
            },
        )

        response = self.client.get(f"/runs/{run.pk}/")

        self.assertContains(response, "Propositions de leads Orange")
        self.assertContains(response, "Réseau multi-sites")
        self.assertContains(response, "Paiement et communication client")
        self.assertContains(response, "Mobilité et M2M")
        self.assertContains(response, "Collaboration et productivité")
        self.assertNotContains(response, "Cybersécurité")
        self.assertContains(response, "Datacenter et continuité")
        self.assertContains(response, "Offres Orange RDC")
        self.assertContains(response, "Hébergement Datacenter")
        self.assertNotContains(response, "Cloud international Orange Business")
        self.assertContains(response, "Combien de sites faut-il relier ?")
