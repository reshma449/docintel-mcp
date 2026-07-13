"""Core data models for the document-intelligence pipeline."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class RouteDecision(str, Enum):
    """Outcome of confidence-threshold routing for an extracted field."""

    AUTO_ACCEPT = "auto_accept"
    NEEDS_REVIEW = "needs_review"
    REJECT = "reject"


@dataclass
class ExtractedField:
    """A single structured field pulled out of a document.

    Attributes:
        name: Canonical field name (e.g. ``invoice_number``).
        value: The extracted raw value, or ``None`` if not found.
        confidence: Score in ``[0.0, 1.0]`` expressing how sure the
            extractor is. Heuristic extractors derive this from pattern
            specificity and surrounding context; LLM extractors can pass
            through model-reported confidence.
        source_snippet: The text neighbourhood the value came from, kept
            so a human reviewer can verify without reopening the document.
    """

    name: str
    value: str | None
    confidence: float
    source_snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractionResult:
    """Everything extracted from one document in one pass."""

    document_id: str
    text: str
    fields: list[ExtractedField] = field(default_factory=list)
    page_count: int = 1
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "page_count": self.page_count,
            "text_chars": len(self.text),
            "fields": [f.to_dict() for f in self.fields],
            "warnings": self.warnings,
        }


@dataclass
class ReviewItem:
    """A field routed to the human review queue.

    Mirrors the operating pattern used in production document pipelines:
    anything the extractor is not confident about goes to a person, with
    enough context attached that review takes seconds, not minutes.
    """

    item_id: str
    document_id: str
    field: ExtractedField
    reason: str
    created_at: float = field(default_factory=time.time)
    resolved: bool = False
    resolved_value: str | None = None

    @classmethod
    def new(cls, document_id: str, fld: ExtractedField, reason: str) -> "ReviewItem":
        return cls(item_id=uuid.uuid4().hex[:12], document_id=document_id, field=fld, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "document_id": self.document_id,
            "field": self.field.to_dict(),
            "reason": self.reason,
            "created_at": self.created_at,
            "resolved": self.resolved,
            "resolved_value": self.resolved_value,
        }
