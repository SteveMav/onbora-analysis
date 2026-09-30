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
            CompanySeed(legal_name="Entreprise Test"), "aucune preuve"
        )

        self.assertEqual([hit.url for hit in hits], [
            "https://example.com/company", "https://news.example/story",
        ])
        self.assertTrue(all(hit.provider == "openai" for hit in hits))
        options = client.responses.create.call_args.kwargs
        self.assertEqual(options["model"], "gpt-6-luna")
        self.assertEqual(options["max_tool_calls"], 1)
        self.assertEqual(options["tools"], [{"type": "web_search", "search_context_size": "low"}])
        self.assertFalse(options["store"])

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
                                   "independent", "À vérifier", "Entreprise Test est mentionnée.")

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
