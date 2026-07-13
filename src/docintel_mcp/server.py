"""The MCP server: document-intelligence tools over FastMCP.

Run directly (``python -m docintel_mcp.server`` or the ``docintel-mcp``
console script) and connect from any MCP client — Claude Desktop,
Claude Code, or your own agent. See README for client configuration.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .confidence import ReviewQueue, Thresholds, route_extraction
from .extraction import run_extraction
from .store import DocumentStore

# --- server state -----------------------------------------------------------

mcp = FastMCP(
    "docintel",
    instructions=(
        "Document-intelligence tools: extract text and structured fields from "
        "documents, route low-confidence fields to a human review queue, and "
        "search previously processed documents."
    ),
)

_store = DocumentStore()
_queue = ReviewQueue(os.environ.get("DOCINTEL_REVIEW_QUEUE", ".docintel/review_queue.jsonl"))
_thresholds = Thresholds(
    accept=float(os.environ.get("DOCINTEL_ACCEPT_THRESHOLD", "0.85")),
    review=float(os.environ.get("DOCINTEL_REVIEW_THRESHOLD", "0.30")),
)


# --- tools -------------------------------------------------------------------


@mcp.tool()
def process_document(path: str) -> dict:
    """Extract text + structured fields from a document (.pdf/.txt/.md),
    route each field by confidence, and index the document for search.

    Returns the routing summary: accepted fields, fields sent to human
    review, and rejected fields.
    """
    result = run_extraction(path)
    _store.add(result.document_id, Path(path).name, result.text)
    summary = route_extraction(result, _queue, _thresholds)
    return {
        "document_id": result.document_id,
        "page_count": result.page_count,
        "warnings": result.warnings,
        "routing": summary,
        "thresholds": {"accept": _thresholds.accept, "review": _thresholds.review},
    }


@mcp.tool()
def search_documents(query: str, top_k: int = 5) -> list[dict]:
    """BM25 keyword search across all documents processed this session."""
    return _store.search(query, top_k=top_k)


@mcp.tool()
def get_document_text(document_id: str, max_chars: int = 4000) -> dict:
    """Return the extracted text of a processed document (truncated)."""
    doc = _store.get(document_id)
    if doc is None:
        return {"error": f"Unknown document_id {document_id!r}. Use list_documents."}
    return {
        "document_id": doc.document_id,
        "name": doc.name,
        "text": doc.text[:max_chars],
        "truncated": len(doc.text) > max_chars,
    }


@mcp.tool()
def list_documents() -> list[dict]:
    """List all documents processed this session."""
    return _store.list_documents()


@mcp.tool()
def review_queue_pending() -> list[dict]:
    """List extraction fields currently awaiting human review."""
    return [item.to_dict() for item in _queue.pending()]


@mcp.tool()
def review_resolve(item_id: str, corrected_value: str) -> dict:
    """Resolve a review item with the human-confirmed value."""
    try:
        item = _queue.resolve(item_id, corrected_value)
    except KeyError as exc:
        return {"error": str(exc)}
    return item.to_dict()


def main() -> None:
    """Entry point: serve over stdio (the standard MCP local transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
