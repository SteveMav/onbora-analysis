from django.test import SimpleTestCase

from research.gemini import GeminiServiceError, validate_summary_payload


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
