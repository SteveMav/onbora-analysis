"""Offline research scenarios with known entity and source outcomes."""

from __future__ import annotations

import hashlib
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase, override_settings

from research.gemini import GeminiServiceError
from research.models import ArspImport, ArspRecord, ResearchRun, RunEvidence, SourceAttempt
from research.openai_research import OpenAIResearchClient
from research.pipeline import execute_research_run
from research.web_research import CompanySeed, PageAssessment, PageFetcher, SearchHit, assess_text


COMPANY = CompanySeed(
    legal_name="Atlas Kivu SARLU",
    rccm="CD/GOM/RCCM/26-B-001",
    province="Nord-Kivu",
    sector="Transport et logistique",
)
CATALOG = Path(__file__).parent / "fixtures" / "orange_catalog.json"


def hit(category: str, url: str, title: str, snippet: str = "") -> SearchHit:
    return SearchHit(category=category, query=category, rank=1, title=title,
                     url=url, snippet=snippet, discovery_score=0)


class FixtureSearch:
    last_warnings = ()

    def __init__(self, by_category: dict[str, list[SearchHit]], events: list[str]) -> None:
        self.by_category = by_category
        self.events = events

    def search(self, spec):
        self.events.append(f"search:{spec.category}")
        return self.by_category.get(spec.category, [])


class FixtureFetcher:
    def __init__(self, pages: dict[str, str], events: list[str]) -> None:
        self.pages = pages
        self.events = events

    def analyze(self, source, company):
        self.events.append(f"fetch:{source.category}")
        text = self.pages.get(source.url)
        if text is None:
            return PageAssessment("Inaccessible", 0, "other", "independent", (), "", source.url,
                                  error="page inaccessible")
        assessment = assess_text(company, source.title, text, source.url)
        return PageAssessment(**{**assessment.__dict__,
                                 "content_hash": hashlib.sha256(text.encode()).hexdigest()})


class FixtureAI:
    model = "fixture-ai"

    def __init__(self, extra: list[SearchHit] | None = None) -> None:
        self.extra = extra or []
        self.search_calls = 0
        self.summary_calls = 0

    def search(self, company, reason):
        self.search_calls += 1
        return self.extra

    def summarize(self, company, evidence):
        self.summary_calls += 1
        ids = [item.evidence_id for item in evidence]
        assert ids
        return {"status": "complete", "model": self.model,
                "overview": {"text": "Une source décrit cette entreprise.", "evidence_ids": ids},
                "key_facts": [], "contradictions": [], "gaps": []}


class FixtureOpenAI(FixtureAI, OpenAIResearchClient):
    model = "gpt-6-luna"


@override_settings(ONBORA_OPENAI_ENABLED=False, ONBORA_GEMINI_ENABLED=False,
                   ONBORA_OFFER_CATALOG_PATH=CATALOG)
class OpenAIPrimaryPipelineTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="openai-kam")
        imported = ArspImport.objects.create(file_name="openai.xlsx", file_hash="a" * 64)
        record = ArspRecord.objects.create(arsp_import=imported, dossier_number="openai-1",
                                          legal_name=COMPANY.legal_name, raw_data={}, normalized_data={})
        self.run = ResearchRun.objects.create(
            source_record=record, requested_by=user, request_fingerprint="b" * 64,
            seed_snapshot={"input_snapshot": {"legal_name": COMPANY.legal_name, "rccm": COMPANY.rccm,
                                              "province": COMPANY.province, "activity_arsp": COMPANY.sector}},
            state=ResearchRun.State.RESEARCHING,
        )
        self.events = []
        self.url = "https://atlas-kivu.example/services"
        self.source = SearchHit(**{**hit("ai_research", self.url, COMPANY.legal_name).__dict__, "provider": "openai"})
        self.text = f"{COMPANY.legal_name} | {COMPANY.rccm} | Transport et logistique, bureaux et dépôts à Goma."

    def execute(self, ai, *, pages=None, search=None):
        return execute_research_run(
            self.run, ai_client=ai,
            search_client=search or FixtureSearch({}, self.events),
            page_fetcher=FixtureFetcher({self.url: self.text} if pages is None else pages, self.events),
        )

    def test_configured_openai_replaces_searx_discovery_and_enrichment(self):
        ai = FixtureOpenAI([self.source])
        with patch.object(OpenAIResearchClient, "from_settings", return_value=ai):
            result = execute_research_run(self.run, search_client=FixtureSearch({}, self.events),
                                          page_fetcher=FixtureFetcher({self.url: self.text}, self.events))
        self.assertEqual(ai.search_calls, 1)
        self.assertEqual(ai.summary_calls, 1)
        self.assertEqual(self.events, ["fetch:ai_research"])
        self.assertEqual(result.identity_status, "confirmed")
        self.assertEqual(result.ai_summary["status"], "complete")
        self.assertEqual(result.result_summary["query_count"], 1)
        self.assertEqual(result.result_summary["discovery_provider"], "openai")
        self.assertEqual(result.result_summary["ai_search_request_count"], 1)
        self.assertEqual(result.result_summary["ai_summary_request_count"], 1)
        self.assertEqual(result.result_summary["profile_query_count"], 0)
        self.assertEqual(result.result_summary["lead_query_count"], 0)
        self.assertEqual(result.result_summary["lead_qualification"]["status"], "complete")
        self.assertEqual(set(result.ai_summary["overview"]["evidence_ids"]),
                         set(result.run_evidence.values_list("evidence_id", flat=True)))
        self.assertFalse(result.source_attempts.filter(provider="searxng").exists())

    def test_reads_ai_sources_even_when_their_title_and_url_do_not_match_the_company(self):
        urls = [f"https://publisher{number}.example/about" for number in range(5)]
        ai = FixtureOpenAI([SearchHit("research", "ai_research", i + 1, "Présentation", url, "", 0, "openai")
                            for i, url in enumerate(urls)])
        result = self.execute(ai, pages={url: self.text for url in urls})
        self.assertEqual(result.result_summary["ai_search_source_count"], 5)
        self.assertEqual(result.result_summary["captured_count"], 5)
        self.assertEqual(ai.search_calls, 1)
        self.assertEqual(ai.summary_calls, 1)

    def test_empty_ai_search_uses_searx_without_retrying_ai_search(self):
        ai = FixtureOpenAI()
        search = FixtureSearch({"registry": [hit("registry", self.url, COMPANY.legal_name, COMPANY.rccm)]}, self.events)
        result = self.execute(ai, search=search)
        self.assertEqual(ai.search_calls, 1)
        self.assertEqual(ai.summary_calls, 1)
        self.assertEqual(result.identity_status, "confirmed")
        self.assertEqual(result.result_summary["discovery_provider"], "searxng")
        self.assertIn("search:registry", self.events)
        self.assertTrue(any("SearXNG de secours" in value for value in result.limitations))

    def test_failed_ai_search_is_recorded_and_searx_sources_are_preserved(self):
        ai = FixtureOpenAI()
        search = FixtureSearch({"registry": [hit("registry", self.url, COMPANY.legal_name, COMPANY.rccm)]}, self.events)
        with patch.object(ai, "search", side_effect=GeminiServiceError("Quota OpenAI atteint.")) as paid_search:
            result = self.execute(ai, search=search)
        paid_search.assert_called_once()
        self.assertTrue(result.source_attempts.filter(provider="openai", status="unavailable").exists())
        self.assertEqual(result.result_summary["captured_count"], 1)
        self.assertEqual(result.state, ResearchRun.State.AWAITING_REVIEW)
        self.assertIn("Quota OpenAI atteint.", result.limitations)

    def test_unrelated_ai_page_does_not_generate_a_summary_or_another_search(self):
        ai = FixtureOpenAI([self.source])
        result = self.execute(ai, pages={self.url: "Une autre entreprise française vend des chaussures."})
        self.assertEqual(ai.search_calls, 1)
        self.assertEqual(ai.summary_calls, 0)
        self.assertEqual(result.ai_summary["status"], "not_generated")
        self.assertEqual(result.result_summary["ai_summary_request_count"], 0)
        self.assertFalse(any(event.startswith("search:") for event in self.events))

    def test_inaccessible_sources_do_not_generate_a_summary(self):
        ai = FixtureOpenAI([self.source])
        result = self.execute(ai, pages={})
        self.assertEqual(ai.search_calls, 1)
        self.assertEqual(ai.summary_calls, 0)
        self.assertEqual(result.result_summary["captured_count"], 0)
        self.assertEqual(result.ai_summary["status"], "not_generated")
        self.assertTrue(result.source_attempts.filter(status="unavailable").exists())

    def test_cancellation_before_discovery_does_not_spend_an_api_call(self):
        self.run.cancellation_requested = True
        self.run.save()
        ai = FixtureOpenAI([self.source])
        result = self.execute(ai)
        self.assertEqual(result.state, ResearchRun.State.CANCELLED)
        self.assertEqual(ai.search_calls, 0)
        self.assertEqual(ai.summary_calls, 0)
        self.assertEqual(self.events, [])

    def test_summary_failure_keeps_verified_evidence(self):
        ai = FixtureOpenAI([self.source])
        with patch.object(ai, "summarize", side_effect=GeminiServiceError("Synthèse indisponible.")) as summary:
            result = self.execute(ai)
        summary.assert_called_once()
        self.assertEqual(result.ai_summary["status"], "failed")
        self.assertEqual(result.result_summary["captured_count"], 1)
        self.assertEqual(result.state, ResearchRun.State.AWAITING_REVIEW)


@override_settings(
    ONBORA_ANALYSIS_LIMIT=3,
    ONBORA_LEAD_ANALYSIS_LIMIT=2,
    ONBORA_OPENAI_ENABLED=False,
    ONBORA_GEMINI_ENABLED=False,
    ONBORA_OFFER_CATALOG_PATH=CATALOG,
)
class PipelineQualityTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="quality-kam")
        imported = ArspImport.objects.create(file_name="quality.xlsx", file_hash="f" * 64)
        record = ArspRecord.objects.create(
            arsp_import=imported, dossier_number="fixture-1", legal_name=COMPANY.legal_name,
            raw_data={"Dénomination": COMPANY.legal_name}, normalized_data={},
        )
        self.run = ResearchRun.objects.create(
            source_record=record, requested_by=user, request_fingerprint="e" * 64,
            seed_snapshot={"input_snapshot": {
                "legal_name": COMPANY.legal_name, "rccm": COMPANY.rccm,
                "province": COMPANY.province, "activity_arsp": COMPANY.sector,
            }}, state=ResearchRun.State.RESEARCHING,
        )

    def test_identity_page_is_fetched_before_lead_search_and_summary_uses_its_evidence(self):
        events: list[str] = []
        registry = "https://arsp.cd/registre/atlas-kivu"
        lead = "https://atlas-kivu.example/implantations"
        search = FixtureSearch({
            "registry": [hit("registry", registry, "Atlas Kivu SARLU | registre", COMPANY.rccm)],
            "lead_network": [hit("lead_network", lead, "Atlas Kivu SARLU | bureaux", COMPANY.legal_name)],
        }, events)
        fetcher = FixtureFetcher({
            registry: f"Atlas Kivu SARLU | {COMPANY.rccm} | Nord-Kivu | Transport et logistique",
            lead: "Atlas Kivu SARLU exploite plusieurs bureaux et dépôts au Nord-Kivu.",
        }, events)
        ai = FixtureAI()

        result = execute_research_run(self.run, search_client=search, page_fetcher=fetcher, ai_client=ai)

        self.assertEqual(result.identity_status, "confirmed")
        self.assertEqual(result.ai_summary["status"], "complete")
        self.assertEqual(ai.search_calls, 0)
        self.assertEqual(ai.summary_calls, 1)
        self.assertLess(events.index("fetch:registry"), events.index("search:lead_network"))
        self.assertEqual(result.result_summary["lead_query_count"], 5)
        self.assertGreaterEqual(result.result_summary["usable_count"], 1)
        self.assertEqual(set(result.ai_summary["overview"]["evidence_ids"]),
                         set(RunEvidence.objects.values_list("evidence_id", flat=True)))

    def test_registry_contact_discovers_website_even_without_search_results(self):
        self.run.seed_snapshot["input_snapshot"].update({
            "legal_name": "1FLUENCE SARLU", "trade_name": "#1FLUENCE",
            "email_arsp": "contact@1fluence.net_x000d_", "province": "Kinshasa",
        })
        self.run.save()
        events = []
        url = "https://1fluence.net/"
        result = execute_research_run(
            self.run, search_client=FixtureSearch({}, events),
            page_fetcher=FixtureFetcher({url: "#1FLUENCE est une agence de marketing et communication à Kinshasa."}, events),
            ai_client=FixtureAI(),
        )
        self.assertEqual(result.identity_status, "confirmed")
        self.assertFalse(result.result_summary["ai_search_attempted"])
        self.assertEqual(result.result_summary["usable_count"], 1)
        self.assertTrue(SourceAttempt.objects.filter(category="seed_website", status="accessible").exists())
        evidence = result.run_evidence.get()
        self.assertEqual(evidence.evidence.relationship, "first_party")
        self.assertIn("communication", evidence.relevant_excerpt)

    def test_many_discovered_homonyms_do_not_unlock_leads_or_generate_a_summary(self):
        events: list[str] = []
        pages = {f"https://other.example/{number}":
                 f"Autre Entreprise SARLU numéro {number} travaille au Nord-Kivu. "
                 "Elle exerce une activité de transport et logistique."
                 for number in range(10)}
        returned = [hit("identity", url, "Atlas Kivu SARLU : résultat", COMPANY.legal_name)
                    for url in pages]
        search = FixtureSearch({"identity": returned}, events)
        foreign = hit("ai_fallback", "https://other.example/foreign", "Atlas Kivu SARLU")
        ai = FixtureAI([foreign])

        result = execute_research_run(self.run, search_client=search,
                                      page_fetcher=FixtureFetcher(pages, events), ai_client=ai)

        self.assertEqual(result.identity_status, "not_found")
        self.assertEqual(result.result_summary["usable_count"], 0)
        self.assertEqual(result.ai_summary["status"], "not_generated")
        self.assertEqual(ai.search_calls, 1)
        self.assertEqual(ai.summary_calls, 0)
        self.assertFalse(any(event.startswith("search:lead_") for event in events))
        self.assertFalse(any(event.startswith("search:profile_") for event in events))
        self.assertGreaterEqual(result.result_summary["unique_count"], 10)
        self.assertEqual(SourceAttempt.objects.filter(status=SourceAttempt.Status.ACCESSIBLE).count(), 2)
        kam, _ = Group.objects.get_or_create(name="kam")
        result.requested_by.groups.add(kam)
        self.client.force_login(result.requested_by)
        response = self.client.get(f"/runs/{result.pk}/")
        self.assertContains(response, "Identité non vérifiée par la recherche")
        self.assertContains(response, "preuves retenues")
        self.assertNotContains(response, '<span class="model-badge">fixture-ai</span>', html=True)

    @override_settings(ONBORA_ANALYSIS_LIMIT=1, ONBORA_RESCUE_ANALYSIS_LIMIT=2)
    def test_second_searx_page_can_rescue_identity_before_paid_ai_search(self):
        events: list[str] = []
        bad_url = "https://a-homonym.example/result"
        good_url = "https://z-registry.example/atlas"
        good_hit = hit("identity", good_url, "Atlas Kivu SARLU", COMPANY.legal_name)
        good_hit = SearchHit(**{**good_hit.__dict__, "rank": 2})
        search = FixtureSearch({"identity": [
            hit("identity", bad_url, "Atlas Kivu SARLU", COMPANY.legal_name),
            good_hit,
        ]}, events)
        fetcher = FixtureFetcher({
            bad_url: "Une autre entreprise offre des services au Nord-Kivu.",
            good_url: f"Atlas Kivu SARLU | {COMPANY.rccm} | Goma, Nord-Kivu",
        }, events)
        ai = FixtureAI()

        result = execute_research_run(self.run, search_client=search, page_fetcher=fetcher, ai_client=ai)

        self.assertEqual(result.identity_status, "confirmed")
        self.assertEqual(result.result_summary["rescue_analyzed_count"], 1)
        self.assertEqual(ai.search_calls, 0)
        self.assertEqual(result.ai_summary["status"], "complete")

    @override_settings(ONBORA_PROFILE_ANALYSIS_LIMIT=1, ONBORA_LEAD_QUALIFICATION_ENABLED=False)
    def test_profile_collects_contacts_after_identity_with_bounded_fetches_without_leads(self):
        events = []
        registry = "https://arsp.cd/registre/atlas"
        contact = "https://atlas-kivu.example/contact"
        extra = "https://atlas-kivu.example/services"
        search = FixtureSearch({
            "registry": [hit("registry", registry, COMPANY.legal_name, COMPANY.rccm)],
            "profile_contact": [hit("profile_contact", contact, COMPANY.legal_name, COMPANY.rccm)],
            "profile_activity": [
                hit("profile_activity", contact, COMPANY.legal_name, COMPANY.rccm),
                hit("profile_activity", extra, COMPANY.legal_name),
            ],
        }, events)
        fetcher = FixtureFetcher({
            registry: f"{COMPANY.legal_name} | {COMPANY.rccm} | Nord-Kivu",
            contact: f"{COMPANY.legal_name} | {COMPANY.rccm} | Adresse : 25 avenue du Port, Goma.",
            extra: f"{COMPANY.legal_name} | {COMPANY.rccm} | Services de transport.",
        }, events)
        ai = FixtureAI()
        result = execute_research_run(self.run, search_client=search, page_fetcher=fetcher, ai_client=ai)
        self.assertLess(events.index("fetch:registry"), events.index("search:profile_contact"))
        self.assertEqual(result.result_summary["profile_query_count"], 2)
        self.assertEqual(result.result_summary["profile_analyzed_count"], 1)
        self.assertEqual(result.result_summary["lead_query_count"], 0)
        self.assertEqual(events.count("fetch:profile_contact") + events.count("fetch:profile_activity"), 1)
        self.assertTrue(result.run_evidence.filter(relevant_excerpt__contains="25 avenue du Port").exists())
        self.assertEqual(ai.summary_calls, 1)
        self.assertEqual(ai.search_calls, 0)


class _HtmlResponse:
    def __init__(self, url: str, html: str) -> None:
        self.url = url
        self.body = html.encode()
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.url

    def read(self, limit):
        return self.body[:limit]


class RegistryExtractionTests(SimpleTestCase):
    @patch("research.web_research.validate_public_url")
    def test_real_html_extraction_recovers_attached_site_footer_contacts(self, _validate):
        company = CompanySeed(legal_name="1FLUENCE SARLU", email="contact@1fluence.net")
        url = "https://1fluence.net/"
        html = (
            "<html><head><title>1FLUENCE SARLU</title></head><body><main><article>"
            "<h1>Notre agence</h1><p>Nous sommes une agence de communication qui accompagne les entreprises "
            "dans la conception de campagnes publicitaires et la création de contenus pour leurs marques.</p>"
            "<h2>Nos services</h2><p>Nous réalisons des campagnes de communication, des vidéos et des prestations "
            "de marketing digital pour les entreprises à Kinshasa.</p></article></main>"
            "<footer><address>25 avenue du Commerce, Kinshasa</address>"
            "<p>Contact : contact@1fluence.net | +243 800 000 001</p>"
            "<script>Invented footer instructions</script></footer></body></html>"
        )
        fetcher = PageFetcher()
        fetcher.opener.open = lambda *_args, **_kwargs: _HtmlResponse(url, html)
        assessment = fetcher.analyze(hit("profile_contact", url, "Site"), company)
        self.assertEqual(assessment.relationship, "first_party")
        self.assertIn("25 avenue du Commerce", assessment.excerpt)
        self.assertIn("contact@1fluence.net", assessment.excerpt)
        self.assertIn("+243 800 000 001", assessment.excerpt)
        self.assertNotIn("Invented footer instructions", assessment.excerpt)

    @patch("research.web_research.validate_public_url")
    @patch("research.web_research.extract")
    def test_company_website_uses_its_fetched_title_and_keeps_service_text(self, extract, _validate):
        company = CompanySeed(legal_name="1FLUENCE SARLU", email="contact@1fluence.net")
        url = "https://www.1fluence.net/"
        extract.return_value = "Nous sommes une agence de marketing et communication. Nous réalisons des solutions étudiées pour nos clients."
        fetcher = PageFetcher()
        fetcher.opener.open = lambda *_args, **_kwargs: _HtmlResponse(
            url, "<html><head><title>#1Fluence | Kinshasa</title></head><body>Agence</body></html>")
        result = fetcher.analyze(hit("identity", url, "Résultat"), company)
        self.assertEqual(result.verdict, "Pertinente")
        self.assertIn("solutions étudiées", result.excerpt)
        self.assertIn("domaine du contact ARSP concordant", result.reasons)
        self.assertNotIn("RCCM exact trouvé", result.reasons)

    @patch("research.web_research.validate_public_url")
    @patch("research.web_research.extract")
    def test_search_title_cannot_establish_ownership_of_an_unrelated_page(self, extract, _validate):
        company = CompanySeed(legal_name="1FLUENCE SARLU", email="contact@1fluence.net")
        url = "https://www.1fluence.net/"
        extract.return_value = "Autre Société exploite désormais ce site internet. Cette page décrit ses propres services de transport."
        fetcher = PageFetcher()
        fetcher.opener.open = lambda *_args, **_kwargs: _HtmlResponse(
            url, "<html><head><title>Autre Société</title></head><body>Transport</body></html>")
        result = fetcher.analyze(hit("identity", url, "1FLUENCE SARLU"), company)
        self.assertEqual(result.verdict, "Hors sujet probable")

    @override_settings(ONBORA_MAX_PAGE_BYTES=1000, ONBORA_MAX_ARSP_PAGE_BYTES=10000)
    @patch("research.web_research.validate_public_url")
    def test_large_arsp_table_uses_only_the_matching_company_row(self, _validate):
        url = "https://backup.arsp.cd/registre-des-entreprises-enregistrees/"
        html = (
            "<html><body>" + ("padding " * 200) +
            "<tr><td>Autre Entreprise SARLU</td><td>CD/GOM/RCCM/26-B-999</td></tr>"
            "<td>Atlas Kivu SARLU</td><td>Transport et logistique</td>"
            f"<td>{COMPANY.rccm}</td><td>Goma, Nord-Kivu</td></tr>"
            "<td>Autre Atlas SARLU</td><td>CD/GOM/RCCM/26-B-001</td></tr>"
            "</body></html>"
        )
        fetcher = PageFetcher()
        fetcher.opener.open = lambda *_args, **_kwargs: _HtmlResponse(url, html)

        result = fetcher.analyze(hit("registry", url, "ARSP - registre"), COMPANY)

        self.assertEqual(result.verdict, "Pertinente")
        self.assertIn(COMPANY.rccm, result.excerpt)
        self.assertNotIn("Autre Entreprise", result.excerpt)
        self.assertNotIn("Autre Atlas", result.excerpt)

    @override_settings(ONBORA_MAX_PAGE_BYTES=1000, ONBORA_MAX_ARSP_PAGE_BYTES=10000)
    @patch("research.web_research.validate_public_url")
    def test_registry_does_not_borrow_rccm_from_the_next_company(self, _validate):
        url = "https://backup.arsp.cd/registre-des-entreprises-enregistrees/"
        html = (
            "<html><body>" + ("padding " * 200) +
            "<td>Atlas Kivu SARLU</td><td>Transport et logistique au Nord-Kivu, Goma</td>"
            "<td>CD/GOM/RCCM/26-B-999</td></tr>"
            f"<td>Autre Entreprise SARLU</td><td>{COMPANY.rccm}</td></tr>"
            "</body></html>"
        )
        fetcher = PageFetcher()
        fetcher.opener.open = lambda *_args, **_kwargs: _HtmlResponse(url, html)

        result = fetcher.analyze(hit("registry", url, "ARSP - registre"), COMPANY)

        self.assertEqual(result.verdict, "À vérifier")
        self.assertNotIn(COMPANY.rccm, result.excerpt)

    @override_settings(ONBORA_MAX_PAGE_BYTES=1000, ONBORA_MAX_ARSP_PAGE_BYTES=10000)
    @patch("research.web_research.validate_public_url")
    def test_large_non_arsp_page_keeps_the_normal_size_limit(self, _validate):
        url = "https://example.org/huge-list"
        fetcher = PageFetcher()
        fetcher.opener.open = lambda *_args, **_kwargs: _HtmlResponse(url, "padding " * 200)

        result = fetcher.analyze(hit("identity", url, "Result"), COMPANY)

        self.assertEqual(result.verdict, "Inaccessible")
        self.assertEqual(result.error, "page trop volumineuse")
