import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook

from app import (
    Company,
    SearxngClient,
    assess_page,
    build_query,
    load_companies,
    source_kind,
    validate_public_url,
)


class CompanyLoadingTests(unittest.TestCase):
    def test_loads_and_sorts_companies_from_arsp_workbook(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "arsp.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Données"
            sheet.append(["Dénomination", "Nom Commercial", "RCCM", "Numéro Dossier", "Activité", "Province"])
            sheet.append(["Zulu SARL", "", "R-2", "D-2", "Transport", "Kinshasa"])
            sheet.append(["Alpha SARL", "Alpha", "R-1", "D-1", "Services", "Lualaba"])
            workbook.save(path)

            companies = load_companies(path)

        self.assertEqual([company.legal_name for company in companies], ["Alpha SARL", "Zulu SARL"])
        self.assertEqual(companies[0].sector, "Services")
        self.assertIn("D-1", companies[0].label)


class QueryTests(unittest.TestCase):
    def test_builds_a_query_from_company_and_optional_context(self):
        query = build_query("Entreprise Test", "Mines", "Lubumbashi cuivre", "CD/LSH/RCCM/1")
        self.assertEqual(query, '"Entreprise Test" "CD/LSH/RCCM/1" Mines Lubumbashi cuivre')

    def test_company_name_is_required(self):
        with self.assertRaises(ValueError):
            build_query("  ")


class PageAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.company = Company(
            legal_name="Entreprise Test Congo",
            trade_name="Test Congo",
            sector="Transport et logistique",
            province="Kinshasa",
            rccm="CD/KIN/RCCM/24-B-001",
            dossier_number="D-1",
        )

    def test_marks_a_page_with_matching_identity_and_context_as_relevant(self):
        assessment = assess_page(
            self.company,
            "Entreprise Test Congo",
            "Entreprise Test Congo propose des services de transport et logistique à Kinshasa.",
            "https://entreprise-test-congo.example/",
        )

        self.assertEqual(assessment.verdict, "Pertinente")
        self.assertGreaterEqual(assessment.score, 6)
        self.assertIn("nom légal trouvé dans la page", assessment.reasons)

    def test_marks_an_unrelated_page_as_probably_irrelevant(self):
        assessment = assess_page(
            self.company,
            "Actualités sportives",
            "Résultats du championnat et calendrier des prochains matchs.",
            "https://sports.example/article",
        )

        self.assertEqual(assessment.verdict, "Hors sujet probable")

    def test_recognises_an_institutional_source(self):
        self.assertEqual(source_kind("https://registre.gouv.cd/entreprise/1", self.company), "Institutionnelle")

    def test_rejects_a_local_address(self):
        with self.assertRaisesRegex(ValueError, "locale ou privée"):
            validate_public_url("http://127.0.0.1/private")


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"results": [{"title": "Résultat", "url": "https://example.com"}]}).encode()


class SearxngClientTests(unittest.TestCase):
    @patch("urllib.request.urlopen", return_value=_FakeResponse())
    def test_requests_json_results(self, urlopen):
        results = SearxngClient().search('"Entreprise Test" Kinshasa')

        self.assertEqual(results[0]["title"], "Résultat")
        requested_url = urlopen.call_args.args[0].full_url
        self.assertIn("format=json", requested_url)
        self.assertIn("q=", requested_url)


if __name__ == "__main__":
    unittest.main()
