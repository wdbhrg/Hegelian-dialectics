from __future__ import annotations

import os
from typing import Dict, List

from knowledge_base import search_chunks

QDRANT_URL = os.environ.get("HEGEL_QDRANT_URL", "http://localhost:6333").strip()
QDRANT_COLLECTION = os.environ.get("HEGEL_QDRANT_COLLECTION", "hegel_chunks").strip()
EMBED_MODEL = os.environ.get("HEGEL_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2").strip()


def retrieve_candidates(query: str, top_k: int = 10) -> List[Dict[str, str]]:
    """
    Quality-first retrieval:
    1) Try Qdrant vector recall
    2) Fallback to local search_chunks
    """
    query = (query or "").strip()
    if not query:
        return []

    # Try qdrant path first
    try:
        from qdrant_client import QdrantClient  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore

        model = SentenceTransformer(EMBED_MODEL)
        vec = model.encode([query], normalize_embeddings=True)[0].tolist()
        client = QdrantClient(url=QDRANT_URL, timeout=10.0)
        hits = client.search(collection_name=QDRANT_COLLECTION, query_vector=vec, limit=max(2, top_k))
        out: List[Dict[str, str]] = []
        for h in hits:
            payload = h.payload or {}
            out.append(
                {
                    "chunk_id": str(payload.get("chunk_id", "")),
                    "doc_path": str(payload.get("doc_path", "")),
                    "text": str(payload.get("text", "")),
                }
            )
        if out:
            return out
    except Exception:
        pass

    # Fallback path (existing local retriever)
    return search_chunks(query, top_k=top_k)

