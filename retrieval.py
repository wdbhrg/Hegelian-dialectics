from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Dict, List, Tuple


def _env_int(key: str, default: int, *, min_v: int, max_v: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return max(min_v, min(max_v, v))
    except ValueError:
        return default


RETRIEVER_MODE = os.environ.get("HEGEL_RETRIEVER_MODE", "hybrid").strip().lower()  # lexical|hybrid|vector
PREFILTER_KEEP_RATIO = _env_int("HEGEL_PREFILTER_KEEP_RATIO", 30, min_v=10, max_v=80) / 100.0
RERANK_TOP_N = _env_int("HEGEL_RERANK_TOP_N", 3, min_v=1, max_v=10)
VEC_MODEL_NAME = os.environ.get("HEGEL_VEC_MODEL", "sentence-transformers/all-MiniLM-L6-v2").strip()


def _tokenize_query(query: str) -> List[str]:
    q = query.strip().lower()
    if not q:
        return []
    latin_tokens = re.findall(r"[a-z0-9_]+", q)
    han = re.sub(r"[^\u4e00-\u9fff]", "", q)
    han_bigrams = [han[i : i + 2] for i in range(max(len(han) - 1, 0))]
    han_unigrams = list(han) if len(han) <= 2 else []
    tokens = latin_tokens + han_bigrams + han_unigrams
    if not tokens:
        tokens = [q]
    dedup: List[str] = []
    seen = set()
    for t in tokens:
        if t and t not in seen:
            seen.add(t)
            dedup.append(t)
    return dedup


def _char_bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _semantic_proxy_score(query: str, text: str) -> float:
    q_han = re.sub(r"[^\u4e00-\u9fff]", "", query.lower())
    t_han = re.sub(r"[^\u4e00-\u9fff]", "", text.lower())
    if not q_han or not t_han:
        return 0.0
    q_set = _char_bigrams(q_han)
    t_set = _char_bigrams(t_han)
    if not q_set or not t_set:
        return 0.0
    inter = len(q_set & t_set)
    union = len(q_set | t_set)
    return inter / union if union else 0.0


@lru_cache(maxsize=1)
def _load_vec_model():
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        return SentenceTransformer(VEC_MODEL_NAME)
    except Exception:
        return None


def _vector_scores(query: str, pool: List[Tuple[int, Dict[str, str]]]) -> Dict[str, float]:
    model = _load_vec_model()
    if model is None or not pool:
        return {}
    try:
        import numpy as np  # type: ignore

        q_emb = model.encode([query], normalize_embeddings=True)
        texts = [str(ch.get("text", "")) for _, ch in pool]
        emb = model.encode(texts, normalize_embeddings=True)
        sims = (emb @ q_emb[0]).tolist()
        out: Dict[str, float] = {}
        for (_, ch), s in zip(pool, sims):
            cid = str(ch.get("chunk_id", ""))
            out[cid] = float(s)
        return out
    except Exception:
        return {}


def retrieve_ranked_chunks(query: str, chunks: List[Dict[str, str]], top_k: int) -> List[Dict[str, str]]:
    q_terms = _tokenize_query(query)
    if not q_terms or not chunks:
        return []

    prefiltered: List[Tuple[int, Dict[str, str]]] = []
    for ch in chunks:
        text = str(ch.get("text", "")).lower()
        lexical_score = 0
        for t in q_terms:
            if t in text:
                weight = 2 if len(t) == 2 else 1
                lexical_score += text.count(t) * weight
        if lexical_score > 0:
            prefiltered.append((lexical_score, ch))
    if not prefiltered:
        return []

    prefiltered.sort(key=lambda x: x[0], reverse=True)
    keep_n = max(12, int(len(prefiltered) * PREFILTER_KEEP_RATIO))
    pool = prefiltered[:keep_n]

    vec_by_id = _vector_scores(query, pool) if RETRIEVER_MODE in {"hybrid", "vector"} else {}
    scored: List[Tuple[float, Dict[str, str]]] = []
    for lexical, ch in pool:
        sem = _semantic_proxy_score(query, str(ch.get("text", "")))
        cid = str(ch.get("chunk_id", ""))
        vec = float(vec_by_id.get(cid, 0.0))
        if RETRIEVER_MODE == "vector":
            score = vec * 100.0 * 0.75 + float(lexical) * 0.25
        elif RETRIEVER_MODE == "lexical":
            score = float(lexical) * 0.85 + sem * 0.15 * 100.0
        else:
            score = float(lexical) * 0.55 + sem * 0.25 * 100.0 + vec * 0.20 * 100.0
        scored.append((score, ch))

    scored.sort(key=lambda x: x[0], reverse=True)
    take_n = min(max(1, top_k), max(RERANK_TOP_N, top_k))
    return [ch for _, ch in scored[:take_n]]

