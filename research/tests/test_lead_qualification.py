from django.test import SimpleTestCase

from research.lead_qualification import (
    LeadEvidence,
    active_rdc_journey_ids,
    available_rdc_offer_ids,
    build_lead_qualification,
)
from research.web_research import CompanySeed


CATALOG = {
    "catalog_version": "orange-test-v1",
    "status": "draft",
    "services": [
        {
            "service_id": "liaison_specialisee_vpn",
            "name": "Liaison Spécialisée VPN",
            "category": "Internet fixe et réseaux",
            "match": {
                "need_keywords": ["réseau multisite"],
                "sectors": [],
                "required_profile_fields": ["locations", "size"],
            },
        },
        {
            "service_id": "api_orange_money",
            "name": "API Orange Money",
            "category": "Orange Money Business",
            "match": {
                "need_keywords": ["paiement en ligne"],
                "sectors": ["commerce"],
                "required_profile_fields": ["sector", "activities"],
            },
        },
        {
            "service_id": "essentiel_m2m",
            "name": "Essentiel M2M",
            "category": "IoT et M2M",
            "match": {
                "need_keywords": ["flotte de véhicules"],
                "sectors": ["transport", "logistique"],
                "required_profile_fields": ["activities", "locations"],
            },
        },
        {
            "service_id": "microsoft_365",
            "name": "Microsoft 365",
            "category": "Cloud et collaboration",
            "match": {
                "need_keywords": ["microsoft 365", "travail hybride"],
                "sectors": [],
                "required_profile_fields": ["size"],
            },
        },
        {
            "service_id": "cyber_diagnostic",
            "name": "Cyber Diagnostic",
            "category": "Cybersécurité",
            "match": {
                "need_keywords": ["cybersécurité", "audit de sécurité"],
                "sectors": [],
                "required_profile_fields": ["activities"],
            },
        },
        {
            "service_id": "hebergement_datacenter",
            "name": "Hébergement Datacenter",
            "category": "Datacenter et infrastructure",
            "match": {
                "need_keywords": ["serveurs", "datacenter"],
                "sectors": [],
                "required_profile_fields": ["activities"],
            },
        },
        {
            "service_id": "global_cloud_portfolio",
            "name": "Cloud international Orange Business",
            "category": "Cloud international",
            "rdc_availability": "to_confirm",
            "match": {
                "need_keywords": ["migration cloud", "reprise après sinistre"],
                "sectors": [],
                "required_profile_fields": ["activities", "locations", "constraints"],
            },
        },
    ],
}


def journey(result, journey_id):
    return next(item for item in result["journeys"] if item["journey_id"] == journey_id)


class LeadQualificationTests(SimpleTestCase):
    def test_marks_a_journey_prioritaire_only_with_two_independent_sources(self):
        company = CompanySeed(legal_name="Transit Congo", sector="Transport et logistique", province="Kinshasa")
        evidence = [
            LeadEvidence(1, "Présentation", "transit.example", "independent", "Une flotte de véhicules dessert plusieurs provinces."),
            LeadEvidence(2, "Marché logistique", "media.example", "independent", "Ses véhicules assurent le transport et la livraison."),
        ]

        result = build_lead_qualification(company, evidence, "confirmed", catalog_payload=CATALOG)
        mobility = journey(result, "mobility_m2m")

        self.assertEqual(result["catalog_version"], "orange-test-v1")
        self.assertEqual(result["market"], "RDC")
        self.assertEqual(len(result["journeys"]), 5)
        self.assertEqual(result["journeys"][0]["verdict"], "prioritaire")
        self.assertEqual(mobility["verdict"], "prioritaire")
        self.assertEqual(mobility["evidence_ids"], [1, 2])
        self.assertEqual(mobility["offers"][0]["service_id"], "essentiel_m2m")

    def test_keeps_sector_only_compatibility_as_low_confidence_exploration(self):
        company = CompanySeed(legal_name="Boutique Congo", sector="Commerce")

        result = build_lead_qualification(company, [], "ambiguous", catalog_payload=CATALOG)
        payments = journey(result, "payments_customer_communication")

        self.assertEqual(payments["verdict"], "a_explorer")
        self.assertEqual(payments["confidence"], "faible")
        self.assertEqual(payments["evidence_ids"], [])
        self.assertTrue(payments["sector_fit"])

    def test_identity_not_found_prevents_a_commercial_priority(self):
        company = CompanySeed(legal_name="Transit Congo", sector="Transport")
        evidence = [
            LeadEvidence(1, "Présentation", "one.example", "independent", "Flotte de véhicules et livraison."),
            LeadEvidence(2, "Profil", "two.example", "independent", "Transport routier avec véhicules."),
        ]

        result = build_lead_qualification(company, evidence, "not_found", catalog_payload=CATALOG)

        self.assertTrue(all(item["verdict"] == "non_qualifiable" for item in result["journeys"]))

    def test_excludes_non_rdc_security_and_global_cloud_offers(self):
        company = CompanySeed(legal_name="Digital Congo", sector="Services numériques", province="Kinshasa")
        evidence = [
            LeadEvidence(
                1,
                "Application Digital Congo",
                "digital.example",
                "independent",
                "L'entreprise exploite une application mobile et une plateforme numérique.",
            ),
            LeadEvidence(
                2,
                "Programme sécurité",
                "security.example",
                "independent",
                "Un audit de sécurité et de cybersécurité couvre ses services en ligne.",
            ),
            LeadEvidence(
                3,
                "Infrastructure",
                "infra.example",
                "independent",
                "Ses serveurs font l'objet d'un projet de migration cloud.",
            ),
        ]

        result = build_lead_qualification(company, evidence, "confirmed", catalog_payload=CATALOG)
        cloud = journey(result, "cloud_datacenter_continuity")
        collaboration = journey(result, "collaboration_productivity")

        self.assertNotIn("cybersecurity", {item["journey_id"] for item in result["journeys"]})
        self.assertEqual(cloud["verdict"], "a_explorer")
        self.assertEqual(
            {offer["service_id"] for offer in cloud["offers"]},
            {"hebergement_datacenter"},
        )
        self.assertTrue(all(offer["market"] == "RDC" for offer in cloud["offers"]))
        self.assertEqual(collaboration["verdict"], "non_qualifiable")

    def test_rdc_policy_is_fail_closed_for_unapproved_catalogue_entries(self):
        self.assertEqual(
            available_rdc_offer_ids(CATALOG),
            {
                "liaison_specialisee_vpn",
                "api_orange_money",
                "essentiel_m2m",
                "microsoft_365",
                "hebergement_datacenter",
            },
        )
        self.assertEqual(
            active_rdc_journey_ids(CATALOG),
            {
                "multisite_network",
                "payments_customer_communication",
                "mobility_m2m",
                "collaboration_productivity",
                "cloud_datacenter_continuity",
            },
        )
