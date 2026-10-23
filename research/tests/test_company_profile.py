from types import SimpleNamespace

from django.test import SimpleTestCase

from research.company_profile import company_profile_view
from research.gemini import validate_summary_payload
from research.web_research import CompanySeed, assess_text, build_profile_query_plan


def source(evidence_id=12, verdict="Pertinente"):
    return SimpleNamespace(
        evidence_id=evidence_id, verdict=verdict,
        evidence=SimpleNamespace(title="Présentation", publisher="atlas.example",
                                 observed_url="https://atlas.example/contact"),
    )


class CompanyProfileTests(SimpleTestCase):
    def test_structured_fields_drop_foreign_and_unsourced_facts(self):
        result = validate_summary_payload({
            "overview": {"text": "Entreprise de logistique.", "evidence_ids": [12]},
            "company_profile": {
                "activity": [{"text": "Transport de marchandises.", "evidence_ids": [12]}],
                "address": [{"text": "Adresse inventée", "evidence_ids": [999]}],
                "contacts": [{"text": "Sans preuve", "evidence_ids": []}],
                "services": "un tableau est requis",
                "unexpected": [{"text": "Hors contrat", "evidence_ids": [12]}],
            },
        }, {12}, "fixture")
        profile = result["company_profile"]
        self.assertEqual(profile["activity"][0]["text"], "Transport de marchandises.")
        self.assertEqual(profile["address"], [])
        self.assertEqual(profile["contacts"], [])
        self.assertEqual(profile["services"], [])
        self.assertNotIn("unexpected", profile)

    def test_registry_is_available_without_ai_and_placeholders_remain_missing(self):
        seed = {"activity_arsp": "Transport_x000d_ et logistique", "address_arsp": "12 avenue du Port",
                "email_arsp": "contact@atlas.example", "phone_arsp": "+243 800 000 001",
                "province": "Kinshasa", "trade_name": "Non renseigné"}
        profile = company_profile_view({"status": "disabled"}, seed, [])
        fields = {field["key"]: field for field in profile["fields"]}
        self.assertEqual(fields["activity"]["declared"], ["Transport et logistique"])
        self.assertEqual(fields["address"]["declared"], ["12 avenue du Port"])
        self.assertEqual(len(fields["contacts"]["declared"]), 2)
        self.assertFalse(fields["description"]["items"])
        self.assertFalse(fields["locations"]["declared"])
        self.assertEqual(profile["identifiers"], [{"label": "Province", "text": "Kinshasa"}])
        seed["activity_arsp"] = "Non spécifié"
        self.assertFalse(company_profile_view({}, seed, [])["fields"][1]["declared"])

    def test_rendered_facts_use_only_usable_run_sources_and_label_uncertainty(self):
        profile = company_profile_view({"status": "complete", "company_profile": {
            "address": [
                {"text": "Adresse du profil homonyme", "evidence_ids": [13]},
                {"text": "Adresse mentionnée", "evidence_ids": [12], "sources": [{"url": "https://evil.example"}]},
                {"text": "Preuve mal formée", "evidence_ids": [[12]]},
            ],
        }}, {"address_arsp": "Ancienne adresse"}, [source(verdict="À vérifier"), source(13, "Hors sujet probable")])
        address = next(field for field in profile["fields"] if field["key"] == "address")
        self.assertEqual(len(address["items"]), 1)
        self.assertTrue(address["items"][0]["uncertain"])
        self.assertEqual(address["items"][0]["sources"][0]["url"], "https://atlas.example/contact")
        self.assertEqual(address["declared"], ["Ancienne adresse"])

    def test_legacy_overview_remains_a_cited_description(self):
        profile = company_profile_view({"status": "complete", "overview": {
            "text": "Présentation historique", "evidence_ids": [12],
        }}, {}, [source()])
        self.assertEqual(profile["fields"][0]["items"][0]["text"], "Présentation historique")

    def test_profile_queries_target_brand_and_country_or_attached_domain(self):
        company = CompanySeed(legal_name="Atlas Kivu SARLU", province="Nord-Kivu")
        plan = build_profile_query_plan(company)
        self.assertEqual(len(plan), 2)
        self.assertTrue(all('"Atlas Kivu" RDC Nord-Kivu' in spec.query for spec in plan))
        attached = CompanySeed(legal_name="1FLUENCE SARLU", email="contact@1fluence.net")
        self.assertTrue(all("site:1fluence.net" in spec.query for spec in build_profile_query_plan(attached)))

    def test_official_excerpt_keeps_late_contacts_without_borrowing_directory_facts(self):
        company = CompanySeed(legal_name="1FLUENCE SARLU", email="contact@1fluence.net")
        text = "1FLUENCE SARLU\nNotre agence accompagne les marques.\n" + "\n".join(
            f"Texte de navigation {index} " + "mot " * 90 for index in range(20)
        ) + "\nNos services : communication et création.\nAdresse : 25 avenue du Commerce, Kinshasa.\nContact : contact@1fluence.net, +243 800 000 001"
        official = assess_text(company, "Site", text, "https://1fluence.net/")
        self.assertEqual(official.verdict, "Pertinente")
        self.assertIn("25 avenue du Commerce", official.excerpt)
        self.assertIn("communication et création", official.excerpt)
        self.assertIn("+243 800 000 001", official.excerpt)
        self.assertLessEqual(len(official.excerpt), 4800)
        one_paragraph = assess_text(company, "Site", text.replace("\n", " "), "https://1fluence.net/")
        self.assertIn("+243 800 000 001", one_paragraph.excerpt)
        directory_text = text.replace("Contact : contact@1fluence.net", "Autre Entreprise SARLU | Contact : contact@other.example")
        directory = assess_text(company, "Annuaire", directory_text, "https://directory.example/companies")
        self.assertNotIn("25 avenue du Commerce", directory.excerpt)
        self.assertNotIn("+243 800 000 001", directory.excerpt)
