import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from research.gemini import SummaryEvidence
from research.openai_research import OpenAIResearchClient
from research.web_research import CompanySeed


class OpenAIResearchTests(SimpleTestCase):
    @patch.object(OpenAIResearchClient, "_client")
    @override_settings(ONBORA_OPENAI_MAX_SEARCH_SOURCES=5)
    def test_search_is_one_bounded_web_call_and_uses_only_returned_sources(self, client_factory):
        client = MagicMock()
        client_factory.return_value.__enter__.return_value = client
        client.responses.create.return_value = SimpleNamespace(output=[
            SimpleNamespace(type="web_search_call", action=SimpleNamespace(sources=[
                SimpleNamespace(url="https://example.com/company"),
                SimpleNamespace(url="https://example.com/company?utm_source=test"),
            ])),
            SimpleNamespace(type="message", content=[SimpleNamespace(annotations=[
                SimpleNamespace(type="url_citation", url="https://news.example/story", title="Article"),
            ])]),
        ])

        hits = OpenAIResearchClient(api_key="test", model="gpt-6-luna").search(
            CompanySeed(legal_name="Entreprise Test", trade_name="Marque Test",
                        rccm="CD/KIN/26-B-001", tax_number="A12345",
                        province="Kinshasa", address="25 avenue du Port",
                        sector="Transport"), "recherche initiale"
        )

        self.assertEqual([hit.url for hit in hits], [
            "https://example.com/company", "https://news.example/story",
        ])
        self.assertTrue(all(hit.provider == "openai" for hit in hits))
        self.assertTrue(all(hit.category == "ai_research" for hit in hits))
        client.responses.create.assert_called_once()
        options = client.responses.create.call_args.kwargs
        self.assertEqual(options["model"], "gpt-6-luna")
        self.assertEqual(options["max_tool_calls"], 1)
        self.assertEqual(options["tools"], [{"type": "web_search", "search_context_size": "low"}])
        self.assertFalse(options["store"])
        for value in ("Marque Test", "CD/KIN/26-B-001", "A12345", "25 avenue du Port", "Transport",
                      "produits et services", "contacts professionnels", "Orange RDC",
                      "seul appel", "N'invente ni fait ni URL"):
            self.assertIn(value, options["input"])

    @patch("openai.OpenAI")
    def test_sdk_does_not_retry_paid_search_requests(self, sdk_factory):
        OpenAIResearchClient(api_key="test", model="gpt-6-luna", timeout=45)._client()
        sdk_factory.assert_called_once_with(api_key="test", timeout=45, max_retries=0)

    @patch.object(OpenAIResearchClient, "_client")
    def test_summary_is_sourced_and_does_not_search_again(self, client_factory):
        client = MagicMock()
        client_factory.return_value.__enter__.return_value = client
        client.responses.create.return_value = SimpleNamespace(output_text=json.dumps({
            "overview": {"text": "Une source mentionne l'entreprise.", "evidence_ids": [12]},
            "key_facts": [{"text": "Fait sans preuve", "evidence_ids": [999]}],
            "contradictions": [],
            "gaps": ["RCCM non confirmé"],
        }))
        evidence = SummaryEvidence(12, "Source", "https://example.com", "example.com", "other",
                                   "independent", "À vérifier", "Entreprise Test est mentionnée. " + "texte " * 250 + "Adresse : 25 avenue du Port.")

        result = OpenAIResearchClient(api_key="test", model="gpt-6-luna").summarize(
            CompanySeed(legal_name="Entreprise Test"), [evidence]
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["overview"]["evidence_ids"], [12])
        self.assertEqual(result["key_facts"], [])
        self.assertNotIn("tools", client.responses.create.call_args.kwargs)
        prompt = client.responses.create.call_args.kwargs["input"]
        self.assertIn('"relationship": "independent"', prompt)
        self.assertIn("Domaine du contact déclaré ARSP", prompt)
        self.assertIn("Adresse : 25 avenue du Port.", prompt)
        schema = client.responses.create.call_args.kwargs["text"]["format"]["schema"]
        self.assertIn("company_profile", schema["required"])
        self.assertFalse(schema["properties"]["company_profile"]["additionalProperties"])
        self.assertIn("address", schema["properties"]["company_profile"]["required"])
