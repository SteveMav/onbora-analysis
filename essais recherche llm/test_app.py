from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from openpyxl import Workbook

from app import (
    Company,
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    GeminiB2BResearcher,
    _provider_error,
    build_research_request,
    extract_interaction_sources,
    load_catalog,
    load_companies,
)


class CompanyLoadingTests(unittest.TestCase):
    def test_loads_and_sorts_companies_from_the_arsp_workbook(self):
        with TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "arsp.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Données"
            sheet.append(["Dénomination", "Nom Commercial", "RCCM", "Numéro Dossier", "Activité", "Province"])
            sheet.append(["Zulu SARL", "", "R-2", "D-2", "Transport", "Kinshasa"])
            sheet.append(["Alpha SARL", "Alpha", "R-1", "D-1", "Services", "Lualaba"])
            workbook.save(workbook_path)

            companies = load_companies(workbook_path)

        self.assertEqual([company.legal_name for company in companies], ["Alpha SARL", "Zulu SARL"])
        self.assertIn("D-1", companies[0].label)


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.company = Company("Entreprise Test Congo", "Test Congo", "Transport", "Kinshasa", "CD/KIN/RCCM/1", "D-1")

    def test_request_contains_identity_and_each_offer(self):
        request = build_research_request(self.company, "- Gestion de flotte\n- Cybersécurité", "Cible Kasaï")

        self.assertIn("Entreprise Test Congo", request)
        self.assertIn("CD/KIN/RCCM/1", request)
        self.assertIn("Gestion de flotte", request)
        self.assertIn("Cible Kasaï", request)

    def test_offer_is_required(self):
        with self.assertRaisesRegex(ValueError, "offre B2B"):
            build_research_request(self.company, "   ")

    def test_system_prompt_requires_evidence_and_does_not_claim_purchase_intent(self):
        self.assertIn("N'invente aucun fait", SYSTEM_PROMPT)
        self.assertIn("intentions d'achat", SYSTEM_PROMPT)
        self.assertIn("Non qualifiable", SYSTEM_PROMPT)
        self.assertIn("CATALOGUE V1", SYSTEM_PROMPT)
        self.assertEqual(DEFAULT_MODEL, "gemini-3.6-flash")


class CatalogLoadingTests(unittest.TestCase):
    def test_loads_catalog_services_and_creates_a_bounded_prompt_block(self):
        with TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "catalog.json"
            catalog_path.write_text(
                """{
                  "services": [{
                    "service_id": "secure-connect",
                    "name": "Connectivité sécurisée",
                    "category": "Réseaux",
                    "description": "Connectivité gérée pour sites distants.",
                    "allowed_benefits": ["Réseau supervisé"],
                    "target_customers": ["Entreprises multi-sites"],
                    "commercial_terms": ["Selon étude"],
                    "prerequisites": ["Éligibilité du site"],
                    "exclusions": ["Aucun engagement de couverture"],
                    "source_url": "https://business.example/connect"
                  }]
                }""",
                encoding="utf-8",
            )

            catalog = load_catalog(catalog_path)

        self.assertEqual(catalog[0].name, "Connectivité sécurisée")
        block = catalog[0].prompt_block()
        self.assertIn("[CATALOGUE V1 — secure-connect]", block)
        self.assertIn("Éligibilité du site", block)


class InteractionSourceTests(unittest.TestCase):
    def test_extracts_deduplicated_url_citations_from_model_output(self):
        interaction = SimpleNamespace(
            steps=[
                SimpleNamespace(
                    type="model_output",
                    content=[
                        SimpleNamespace(
                            type="text",
                            annotations=[
                                SimpleNamespace(type="url_citation", url="https://example.com/a", title="Source A"),
                                SimpleNamespace(type="url_citation", url="https://example.com/a", title="Duplicate"),
                                SimpleNamespace(type="url_citation", url="ftp://example.com/no", title="Ignored"),
                                SimpleNamespace(type="url_citation", url="https://example.org/b", title="Source B"),
                            ],
                        )
                    ],
                )
            ]
        )

        sources = extract_interaction_sources(interaction)

        self.assertEqual([(source.source_id, source.title) for source in sources], [(1, "Source A"), (2, "Source B")])


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.interactions = self
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class GeminiResearcherTests(unittest.TestCase):
    def test_returns_model_text_and_grounded_sources_without_network(self):
        response = SimpleNamespace(
            output_text="## Décision de prospection\nÀ explorer.",
            steps=[
                SimpleNamespace(
                    type="model_output",
                    content=[
                        SimpleNamespace(
                            type="text",
                            annotations=[SimpleNamespace(type="url_citation", url="https://example.com", title="Exemple")],
                        )
                    ],
                )
            ],
        )
        client = _FakeClient(response)
        researcher = GeminiB2BResearcher("test-key", "gemini-test", client_factory=lambda: client)
        company = Company("Entreprise Test", "", "Services", "Kinshasa", "", "D-1")

        report = researcher.research(company, "- Audit numérique")

        self.assertEqual(report.text, "## Décision de prospection\nÀ explorer.")
        self.assertEqual(report.sources[0].url, "https://example.com")
        self.assertEqual(client.calls[0]["model"], "gemini-test")
        self.assertIn("Audit numérique", client.calls[0]["input"])
        self.assertEqual(client.calls[0]["tools"], [{"type": "google_search"}])
        self.assertFalse(client.calls[0]["store"])

    def test_explains_that_a_429_is_a_quota_problem_not_an_invalid_key(self):
        error = type("QuotaError", (Exception,), {"status_code": 429})("quota exceeded")

        message = str(_provider_error(error))

        self.assertIn("clé est reconnue", message)
        self.assertIn("quota Gemini", message)


if __name__ == "__main__":
    unittest.main()
