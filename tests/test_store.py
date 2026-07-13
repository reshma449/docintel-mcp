"""Tests for the BM25 document store."""

import unittest

from docintel_mcp.store import DocumentStore, tokenize


class TestTokenize(unittest.TestCase):
    def test_lowercases_and_splits(self):
        self.assertEqual(tokenize("Invoice #INV-20441, Total: $4,570"), ["invoice", "inv", "20441", "total", "4", "570"])


class TestDocumentStore(unittest.TestCase):
    def setUp(self):
        self.store = DocumentStore()
        self.store.add("d1", "invoice_acme.txt", "ACME invoice for bearing assembly, total due 4570")
        self.store.add("d2", "contract_beta.txt", "Beta Corp master services agreement, renewal terms")
        self.store.add("d3", "invoice_beta.txt", "Beta Corp invoice, sensor modules, total due 122")

    def test_len_and_list(self):
        self.assertEqual(len(self.store), 3)
        self.assertEqual(len(self.store.list_documents()), 3)

    def test_search_ranks_relevant_first(self):
        results = self.store.search("acme invoice")
        self.assertEqual(results[0]["document_id"], "d1")

    def test_search_multiple_hits(self):
        results = self.store.search("invoice")
        ids = [r["document_id"] for r in results]
        self.assertIn("d1", ids)
        self.assertIn("d3", ids)
        self.assertNotIn("d2", ids)

    def test_search_no_match(self):
        self.assertEqual(self.store.search("zebra quantum"), [])

    def test_search_empty_store(self):
        self.assertEqual(DocumentStore().search("anything"), [])

    def test_preview_truncated(self):
        results = self.store.search("invoice")
        self.assertLessEqual(len(results[0]["preview"]), 160)


if __name__ == "__main__":
    unittest.main()
