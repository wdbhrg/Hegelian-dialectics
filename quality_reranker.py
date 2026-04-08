from __future__ import annotations

import os
from typing import Dict, List, Tuple

RERANK_MODEL = os.environ.get("HEGEL_RERANK_MODEL", "BAAI/bge-reranker-base").strip()


def rerank_candidates(query: str, candidates: List[Dict[str, str]], top_k: int = 5) -> List[Dict[str, str]]:
    if not query.strip() or not candidates:
        return []

    # Quality-first reranker (cross-encoder)
    try:
        from sentence_transformers import CrossEncoder  # type: ignore

        model = CrossEncoder(RERANK_MODEL)
        pairs = [[query, str(c.get("text", ""))] for c in candidates]
        scores = model.predict(pairs).tolist()
        ranked: List[Tuple[float, Dict[str, str]]] = []
        for c, s in zip(candidates, scores):
            ranked.append((float(s), c))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in ranked[: max(1, top_k)]]
    except Exception:
        # Fallback: keep input order
        return candidates[: max(1, top_k)]

