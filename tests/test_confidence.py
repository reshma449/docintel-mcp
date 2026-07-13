"""Tests for threshold routing and the review queue."""

import tempfile
import unittest
from pathlib import Path

from docintel_mcp.confidence import ReviewQueue, Thresholds, route_extraction, route_field
from docintel_mcp.models import ExtractedField, ExtractionResult, RouteDecision


def fld(name="invoice_number", value="INV-1", confidence=0.9):
    return ExtractedField(name=name, value=value, confidence=confidence)


class TestThresholds(unittest.TestCase):
    def test_invalid_ordering_rejected(self):
        with self.assertRaises(ValueError):
            Thresholds(accept=0.3, review=0.8)

    def test_route_accept(self):
        self.assertIs(route_field(fld(confidence=0.9)), RouteDecision.AUTO_ACCEPT)

    def test_route_review(self):
        self.assertIs(route_field(fld(confidence=0.5)), RouteDecision.NEEDS_REVIEW)

    def test_route_reject_low_confidence(self):
        self.assertIs(route_field(fld(confidence=0.1)), RouteDecision.REJECT)

    def test_route_reject_missing_value(self):
        self.assertIs(route_field(fld(value=None, confidence=0.99)), RouteDecision.REJECT)

    def test_boundary_is_inclusive_on_accept(self):
        t = Thresholds(accept=0.85, review=0.30)
        self.assertIs(route_field(fld(confidence=0.85), t), RouteDecision.AUTO_ACCEPT)
        self.assertIs(route_field(fld(confidence=0.30), t), RouteDecision.NEEDS_REVIEW)


class TestReviewQueue(unittest.TestCase):
    def test_add_pending_resolve_and_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "queue.jsonl"
            q = ReviewQueue(path)
            item = q.add("doc1", fld(confidence=0.5), reason="low confidence")
            self.assertEqual(len(q.pending()), 1)

            q.resolve(item.item_id, "INV-CORRECTED")
            self.assertEqual(len(q.pending()), 0)

            # Reload from disk: state survives process restarts.
            q2 = ReviewQueue(path)
            self.assertEqual(len(q2.pending()), 0)
            reloaded = [i for i in q2._items.values()][0]
            self.assertEqual(reloaded.resolved_value, "INV-CORRECTED")

    def test_resolve_unknown_id_raises(self):
        with tempfile.TemporaryDirectory() as td:
            q = ReviewQueue(Path(td) / "queue.jsonl")
            with self.assertRaises(KeyError):
                q.resolve("nope", "x")


class TestRouteExtraction(unittest.TestCase):
    def test_summary_buckets(self):
        result = ExtractionResult(
            document_id="doc9",
            text="...",
            fields=[
                fld("invoice_number", "INV-1", 0.95),
                fld("date", "2026-01-01", 0.50),
                fld("po_number", None, 0.0),
            ],
        )
        with tempfile.TemporaryDirectory() as td:
            q = ReviewQueue(Path(td) / "queue.jsonl")
            summary = route_extraction(result, q)
            self.assertEqual(len(summary["accepted"]), 1)
            self.assertEqual(len(summary["review"]), 1)
            self.assertEqual(len(summary["rejected"]), 1)
            self.assertEqual(len(q.pending()), 1)
            self.assertIn("below accept threshold", q.pending()[0].reason)


if __name__ == "__main__":
    unittest.main()
