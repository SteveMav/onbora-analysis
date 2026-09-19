from django.test import SimpleTestCase

from research.sector_segmentation import SectorEvidence, build_sector_segmentation
from research.web_research import CompanySeed


class SectorSegmentationTests(SimpleTestCase):
    def test_corroborates_the_arsp_sector_with_public_evidence(self):
        company = CompanySeed(legal_name="Transit Congo", sector="Transport et logistique")
        evidence = [
            SectorEvidence(
                12,
                "Transit Congo — nos activités",
                "transit.example",
                "first_party",
                "L'entreprise assure le transport, le fret et la logistique en RDC.",
            )
        ]

        result = build_sector_segmentation(company, evidence, "confirmed")

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["primary"]["segment_id"], "transport_logistics")
        self.assertEqual(result["primary"]["confidence"], "élevée")
        self.assertEqual(result["primary"]["evidence_ids"], [12])

    def test_can_classify_from_two_independent_sources_when_arsp_activity_is_missing(self):
        company = CompanySeed(legal_name="Kivu Bank")
        evidence = [
            SectorEvidence(1, "Kivu Bank", "one.example", "independent", "Une banque commerciale congolaise."),
            SectorEvidence(2, "Profil Kivu Bank", "two.example", "independent", "Institution bancaire et services financiers."),
        ]

        result = build_sector_segmentation(company, evidence, "probable")

        self.assertEqual(result["primary"]["segment_id"], "financial_services")
        self.assertEqual(result["primary"]["confidence"], "élevée")
        self.assertEqual(result["primary"]["publisher_count"], 2)

    def test_exposes_secondary_activity_when_scores_are_close(self):
        company = CompanySeed(legal_name="Mine Logistics", sector="Transport et logistique minière")

        result = build_sector_segmentation(company, [], "ambiguous")

        self.assertEqual(result["primary"]["segment_id"], "mining_extraction")
        self.assertIn("transport_logistics", {item["segment_id"] for item in result["alternatives"]})

    def test_keeps_an_unknown_state_instead_of_forcing_a_sector(self):
        company = CompanySeed(legal_name="Alpha Congo", sector="Activités diverses")

        result = build_sector_segmentation(company, [], "ambiguous")

        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["primary"])
