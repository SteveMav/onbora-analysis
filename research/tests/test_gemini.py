from django.test import SimpleTestCase
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from research.gemini import GeminiResearchClient, GeminiServiceError, validate_summary_payload
from research.web_research import CompanySeed


class GeminiSummaryValidationTests(SimpleTestCase):
    def test_drops_claims_that_do_not_reference_evidence_from_the_run(self):
        result = validate_summary_payload(
            {
                "overview": {"text": "Résumé vérifié", "evidence_ids": [12]},
                "key_facts": [
                    {"text": "Fait vérifié", "evidence_ids": [12]},
                    {"text": "Fait étranger", "evidence_ids": [999]},
                ],
                "contradictions": [],
                "gaps": ["Adresse récente inconnue"],
            },
            {12},
            "gemini-test-fast",
        )

        self.assertEqual(result["key_facts"], [{"text": "Fait vérifié", "evidence_ids": [12]}])

    def test_rejects_an_overview_without_a_valid_source(self):
        with self.assertRaises(GeminiServiceError):
            validate_summary_payload(
                {"overview": {"text": "Non sourcé", "evidence_ids": [999]}},
                {12},
                "gemini-test-fast",
            )


class GeminiGroundedSearchTests(SimpleTestCase):
    @patch.object(GeminiResearchClient, "_client")
    def test_searches_three_angles_and_only_returns_grounded_urls(self, client_factory):
        client = MagicMock()
        client_factory.return_value.__enter__.return_value = client

        def response(url):
            return SimpleNamespace(candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(
                grounding_chunks=[SimpleNamespace(web=SimpleNamespace(uri=url, title="Source publique"))],
            ))], text="Affirmation sans source à ignorer")

        client.models.generate_content.side_effect = [
            response("https://registry.example/company"),
            response("https://registry.example/company"),
            response("https://news.example/company"),
        ]
        research = GeminiResearchClient(api_key="test", model="gemini-test")

        hits = research.search(CompanySeed(legal_name="Entreprise Test Congo"), "aucune preuve")

        self.assertEqual(client.models.generate_content.call_count, 3)
        self.assertEqual([hit.url for hit in hits], [
            "https://registry.example/company", "https://news.example/company",
        ])
        self.assertTrue(all(hit.provider == "gemini" for hit in hits))
