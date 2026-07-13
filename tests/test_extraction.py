"""Tests for text and field extraction."""

import tempfile
import unittest
from pathlib import Path

from docintel_mcp.extraction import PatternFieldExtractor, extract_text, run_extraction

INVOICE_TEXT = """\
ACME Industrial Supplies
Invoice Number: INV-20441
Invoice Date: 2026-05-14
PO Number: PO-88123
Billed by: ACME Industrial Supplies Ltd

Item                 Qty   Price
Bearing assembly      12   $340.00
Sensor module          4   $122.50

Total Due: $4,570.00
"""


class TestExtractText(unittest.TestCase):
    def test_txt_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "invoice.txt"
            p.write_text(INVOICE_TEXT, encoding="utf-8")
            text, pages, warnings = extract_text(p)
        self.assertIn("INV-20441", text)
        self.assertEqual(pages, 1)
        self.assertEqual(warnings, [])

    def test_unsupported_suffix_raises(self):
        with self.assertRaises(ValueError):
            extract_text("document.docx")

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            extract_text("does_not_exist.txt")


class TestPatternFieldExtractor(unittest.TestCase):
    def setUp(self):
        self.fields = {f.name: f for f in PatternFieldExtractor().extract(INVOICE_TEXT)}

    def test_anchored_invoice_number_high_confidence(self):
        f = self.fields["invoice_number"]
        self.assertEqual(f.value, "INV-20441")
        self.assertGreaterEqual(f.confidence, 0.85)

    def test_date_extracted(self):
        self.assertEqual(self.fields["date"].value, "2026-05-14")

    def test_total_amount_extracted(self):
        self.assertEqual(self.fields["total_amount"].value, "$4,570.00")

    def test_snippet_present_for_reviewer(self):
        self.assertIn("INV-20441", self.fields["invoice_number"].source_snippet)

    def test_missing_field_zero_confidence(self):
        fields = {f.name: f for f in PatternFieldExtractor().extract("nothing to see here")}
        self.assertIsNone(fields["invoice_number"].value)
        self.assertEqual(fields["invoice_number"].confidence, 0.0)

    def test_bare_match_gets_low_confidence(self):
        # A number with no anchor keyword should score below anchored matches.
        fields = {f.name: f for f in PatternFieldExtractor().extract("ref 55512 only")}
        f = fields["invoice_number"]
        self.assertIsNotNone(f.value)
        self.assertLess(f.confidence, 0.85)


class TestRunExtraction(unittest.TestCase):
    def test_end_to_end_txt(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "invoice.txt"
            p.write_text(INVOICE_TEXT, encoding="utf-8")
            result = run_extraction(p)
        self.assertEqual(result.page_count, 1)
        names = {f.name for f in result.fields}
        self.assertIn("invoice_number", names)
        self.assertTrue(result.document_id)


if __name__ == "__main__":
    unittest.main()
