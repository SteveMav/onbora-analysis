from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from openpyxl import Workbook

from research.models import ArspImport, ArspRecord


HEADERS = ["Dénomination", "RCCM", "Numéro Dossier", "Adresse", "Téléphone", "Email"]


def make_workbook(path: Path, rows: list[list[str]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Données"
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


class ImportArspTests(TestCase):
    def test_import_preserves_raw_values_and_creates_normalized_variants(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "arsp.xlsx"
            make_workbook(path, [["  Société  Exemple ", " RCCM-1 ", " D-001 ", " Avenue  1 ", " 081 ", " INFO@EXAMPLE.CD "]])
            call_command("import_arsp", path)

        record = ArspRecord.objects.get()
        self.assertEqual(record.raw_data["Dénomination"], "  Société  Exemple ")
        self.assertEqual(record.normalized_data["Dénomination"], "société exemple")
        self.assertEqual(record.dossier_number, "d-001")
        self.assertIn("normalization_available:Dénomination", record.warnings)
        self.assertEqual(ArspImport.objects.get().validation_report["row_count"], 1)

    def test_duplicate_dossier_rejects_the_entire_import(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "arsp.xlsx"
            make_workbook(path, [
                ["Société A", "R-1", "D-001", "", "", ""],
                ["Société B", "R-1", "D-001", "", "", ""],
            ])
            with self.assertRaises(CommandError):
                call_command("import_arsp", path)

        self.assertEqual(ArspImport.objects.count(), 0)
        self.assertEqual(ArspRecord.objects.count(), 0)
