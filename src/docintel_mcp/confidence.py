"""Confidence-threshold routing and the human review queue.

This module encodes the human-in-the-loop pattern used in production
document pipelines: every extracted field carries a confidence score,
and a router sorts fields into three buckets —

* ``auto_accept``  — confident enough to flow straight into analytics
* ``needs_review`` — a person confirms or corrects it (seconds of work)
* ``reject``       — too weak to be worth a reviewer's time

Thresholds are explicit, tunable, and auditable. The review queue
persists to JSONL so a reviewer UI (or a spreadsheet) can consume it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import ExtractedField, ExtractionResult, ReviewItem, RouteDecision


@dataclass(frozen=True)
class Thresholds:
    """Routing thresholds. ``accept > review`` must hold."""

    accept: float = 0.85
    review: float = 0.30

    def __post_init__(self) -> None:
        if not (0.0 <= self.review < self.accept <= 1.0):
            raise ValueError(
                f"Require 0 <= review < accept <= 1, got review={self.review}, accept={self.accept}"
            )


def route_field(fld: ExtractedField, thresholds: Thresholds = Thresholds()) -> RouteDecision:
    """Route a single field by its confidence score."""
    if fld.value is None:
        return RouteDecision.REJECT
    if fld.confidence >= thresholds.accept:
        return RouteDecision.AUTO_ACCEPT
    if fld.confidence >= thresholds.review:
        return RouteDecision.NEEDS_REVIEW
    return RouteDecision.REJECT


class ReviewQueue:
    """A JSONL-backed queue of fields awaiting human review."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, ReviewItem] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            item = ReviewItem(
                item_id=raw["item_id"],
                document_id=raw["document_id"],
                field=ExtractedField(**raw["field"]),
                reason=raw["reason"],
                created_at=raw["created_at"],
                resolved=raw["resolved"],
                resolved_value=raw.get("resolved_value"),
            )
            self._items[item.item_id] = item

    def _flush(self) -> None:
        lines = [json.dumps(i.to_dict()) for i in self._items.values()]
        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def add(self, document_id: str, fld: ExtractedField, reason: str) -> ReviewItem:
        item = ReviewItem.new(document_id, fld, reason)
        self._items[item.item_id] = item
        self._flush()
        return item

    def pending(self) -> list[ReviewItem]:
        return [i for i in self._items.values() if not i.resolved]

    def resolve(self, item_id: str, corrected_value: str) -> ReviewItem:
        if item_id not in self._items:
            raise KeyError(f"No review item {item_id!r}")
        item = self._items[item_id]
        item.resolved = True
        item.resolved_value = corrected_value
        self._flush()
        return item


def route_extraction(
    result: ExtractionResult,
    queue: ReviewQueue,
    thresholds: Thresholds = Thresholds(),
) -> dict[str, list[dict]]:
    """Route every field in an extraction result; enqueue review items.

    Returns a summary dict with ``accepted``, ``review``, ``rejected``
    lists — the shape an MCP client (or a dashboard) wants to display.
    """
    summary: dict[str, list[dict]] = {"accepted": [], "review": [], "rejected": []}
    for fld in result.fields:
        decision = route_field(fld, thresholds)
        if decision is RouteDecision.AUTO_ACCEPT:
            summary["accepted"].append(fld.to_dict())
        elif decision is RouteDecision.NEEDS_REVIEW:
            item = queue.add(
                result.document_id,
                fld,
                reason=f"confidence {fld.confidence:.2f} below accept threshold {thresholds.accept:.2f}",
            )
            summary["review"].append(item.to_dict())
        else:
            summary["rejected"].append(fld.to_dict())
    return summary
