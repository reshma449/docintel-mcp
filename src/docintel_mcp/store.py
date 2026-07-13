"""In-memory document store with BM25 keyword search.

Small on purpose: no vector database required to demonstrate the
retrieval pattern. The scoring is standard BM25 (k1/b defaults), which
outperforms naive TF matching on short business documents and is fully
deterministic — handy for tests and for explaining rankings to
stakeholders.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class StoredDocument:
    document_id: str
    name: str
    text: str
    tokens: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tokens:
            self.tokens = tokenize(self.text)


class DocumentStore:
    """Add documents, then search them with BM25 ranking."""

    K1 = 1.5
    B = 0.75

    def __init__(self) -> None:
        self._docs: dict[str, StoredDocument] = {}

    def add(self, document_id: str, name: str, text: str) -> None:
        self._docs[document_id] = StoredDocument(document_id, name, text)

    def get(self, document_id: str) -> StoredDocument | None:
        return self._docs.get(document_id)

    def __len__(self) -> int:
        return len(self._docs)

    def list_documents(self) -> list[dict]:
        return [
            {"document_id": d.document_id, "name": d.name, "chars": len(d.text)}
            for d in self._docs.values()
        ]

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Rank stored documents against ``query`` with BM25."""
        if not self._docs:
            return []
        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        n = len(self._docs)
        avg_len = sum(len(d.tokens) for d in self._docs.values()) / n

        # Document frequency per query token.
        df = {
            t: sum(1 for d in self._docs.values() if t in d.tokens)
            for t in set(q_tokens)
        }

        scored: list[tuple[float, StoredDocument]] = []
        for doc in self._docs.values():
            score = 0.0
            for t in q_tokens:
                tf = doc.tokens.count(t)
                if tf == 0 or df[t] == 0:
                    continue
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                denom = tf + self.K1 * (1 - self.B + self.B * len(doc.tokens) / avg_len)
                score += idf * (tf * (self.K1 + 1)) / denom
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {
                "document_id": d.document_id,
                "name": d.name,
                "score": round(s, 4),
                "preview": " ".join(d.text.split())[:160],
            }
            for s, d in scored[:top_k]
        ]
