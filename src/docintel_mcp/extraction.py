"""Text and structured-field extraction.

The extractors here are deliberately dependency-light: PDF text layers
via ``pypdf`` and heuristic field extraction via anchored regex patterns
with confidence scoring. The design point is the *pipeline shape* —
extract → score → route — which is identical whether the extractor
behind it is a regex, a cloud OCR API, or an LLM. Swap in a heavier
extractor by implementing :class:`FieldExtractor`.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader

from .models import ExtractedField, ExtractionResult

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md"}


def extract_text(path: str | Path) -> tuple[str, int, list[str]]:
    """Extract raw text from a document.

    Returns ``(text, page_count, warnings)``. For PDFs this reads the
    embedded text layer; scanned PDFs with no text layer produce a
    warning rather than a silent empty result, because silent empties
    are how bad data sneaks into downstream analytics.
    """
    p = Path(path)
    if p.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {p.suffix!r}. Supported: {sorted(SUPPORTED_SUFFIXES)}")
    if not p.exists():
        raise FileNotFoundError(f"No such document: {p}")

    warnings: list[str] = []
    if p.suffix.lower() == ".pdf":
        reader = PdfReader(str(p))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages)
        if not text.strip():
            warnings.append(
                "PDF has no extractable text layer (likely a scan). "
                "Run OCR upstream or supply a text-layer PDF."
            )
        return text, len(reader.pages), warnings

    text = p.read_text(encoding="utf-8", errors="replace")
    return text, 1, warnings


class FieldExtractor(Protocol):
    """Anything that can turn document text into scored fields."""

    def extract(self, text: str) -> list[ExtractedField]: ...


class PatternFieldExtractor:
    """Regex-based field extractor with context-aware confidence scores.

    Confidence heuristic:
      * base score when the value pattern matches at all
      * bonus when an anchor keyword (e.g. "Invoice #") appears within
        the context window before the value
      * penalty when several competing candidates are found, since
        ambiguity is exactly what humans should adjudicate
    """

    #: (field_name, anchor_regex, value_regex)
    DEFAULT_PATTERNS: list[tuple[str, str, str]] = [
        ("invoice_number", r"invoice\s*(?:no\.?|number|#)?", r"[A-Z]{0,4}-?\d{3,10}"),
        ("date", r"(?:invoice\s+)?date[d]?", r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}"),
        ("total_amount", r"(?:grand\s+)?total(?:\s+due)?", r"[$€£]?\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?"),
        ("vendor", r"(?:from|vendor|billed\s+by|supplier)\s*:?", r"[A-Z][A-Za-z0-9&.,' -]{2,60}"),
        ("po_number", r"p\.?o\.?\s*(?:no\.?|number|#)?", r"[A-Z]{0,4}-?\d{3,10}"),
    ]

    BASE_CONFIDENCE = 0.45
    ANCHOR_BONUS = 0.45
    AMBIGUITY_PENALTY = 0.15
    CONTEXT_WINDOW = 48  # chars of snippet kept for the reviewer

    def __init__(self, patterns: list[tuple[str, str, str]] | None = None) -> None:
        self.patterns = patterns or self.DEFAULT_PATTERNS

    def extract(self, text: str) -> list[ExtractedField]:
        fields: list[ExtractedField] = []
        for name, anchor_re, value_re in self.patterns:
            fields.append(self._extract_one(text, name, anchor_re, value_re))
        return fields

    def _extract_one(self, text: str, name: str, anchor_re: str, value_re: str) -> ExtractedField:
        anchored = re.compile(
            rf"({anchor_re})\s*:?\s*({value_re})", re.IGNORECASE
        )
        anchored_matches = list(anchored.finditer(text))

        if anchored_matches:
            m = anchored_matches[0]
            confidence = min(1.0, self.BASE_CONFIDENCE + self.ANCHOR_BONUS)
            if len(anchored_matches) > 1:
                confidence -= self.AMBIGUITY_PENALTY
            snippet = self._snippet(text, m.start(), m.end())
            return ExtractedField(name=name, value=m.group(2).strip(), confidence=round(confidence, 2), source_snippet=snippet)

        # Fall back to a bare value match anywhere — low confidence by design.
        bare = list(re.finditer(value_re, text))
        if bare and name != "vendor":  # bare vendor matches are noise
            m = bare[0]
            confidence = self.BASE_CONFIDENCE
            if len(bare) > 1:
                confidence -= self.AMBIGUITY_PENALTY
            snippet = self._snippet(text, m.start(), m.end())
            return ExtractedField(name=name, value=m.group(0).strip(), confidence=round(max(confidence, 0.05), 2), source_snippet=snippet)

        return ExtractedField(name=name, value=None, confidence=0.0, source_snippet="")

    def _snippet(self, text: str, start: int, end: int) -> str:
        lo = max(0, start - self.CONTEXT_WINDOW)
        hi = min(len(text), end + self.CONTEXT_WINDOW)
        return " ".join(text[lo:hi].split())


def run_extraction(path: str | Path, extractor: FieldExtractor | None = None) -> ExtractionResult:
    """Full extraction pass over one document: text + scored fields."""
    text, page_count, warnings = extract_text(path)
    extractor = extractor or PatternFieldExtractor()
    fields = extractor.extract(text) if text.strip() else []
    return ExtractionResult(
        document_id=uuid.uuid4().hex[:12],
        text=text,
        fields=fields,
        page_count=page_count,
        warnings=warnings,
    )
