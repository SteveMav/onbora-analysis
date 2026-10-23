import json

from django.test import SimpleTestCase
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from research.gemini import GeminiResearchClient, GeminiServiceError, SummaryEvidence, validate_summary_payload
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
    def test_summary_produces_a_structured_profile_with_the_shared_schema(self, client_factory):
        client = MagicMock()
        client_factory.return_value.__enter__.return_value = client
        client.models.generate_content.return_value.text = json.dumps({
            "overview": {"text": "Entreprise de transport", "evidence_ids": [12]},
            "company_profile": {"address": [{"text": "25 avenue du Port", "evidence_ids": [12]}]},
        })
        result = GeminiResearchClient(api_key="test", model="gemini-test").summarize(
            CompanySeed(legal_name="Entreprise Test"),
            [SummaryEvidence(12, "Contacts", "https://example.com/contact", "example.com",
                             "other", "independent", "Pertinente", "Entreprise Test | 25 avenue du Port")],
        )
        self.assertEqual(result["company_profile"]["address"][0]["text"], "25 avenue du Port")
        options = client.models.generate_content.call_args.kwargs
        self.assertIn("company_profile", options["config"]["response_json_schema"]["required"])
        self.assertIn("- contacts : site, email et téléphone", options["contents"])
        self.assertNotIn("tools", options["config"])

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
