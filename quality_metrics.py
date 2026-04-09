from __future__ import annotations

from typing import Dict, List

from quality_schema import REQUIRED_KEYS


def structure_completeness(payload: Dict[str, object]) -> float:
    hit = sum(1 for k in REQUIRED_KEYS if k in payload and str(payload.get(k, "")).strip() != "")
    return hit / len(REQUIRED_KEYS)


def field_duplicate_rate(payload: Dict[str, object]) -> float:
    keys = [
        "stage_explanation",
        "thesis",
        "antithesis",
        "false_synthesis",
        "true_synthesis",
        "contradiction",
        "next_stage",
    ]
    vals: List[str] = []
    for k in keys:
        vals.append(" ".join(str(payload.get(k, "")).strip().lower().split()))
    non_empty = [x for x in vals if x]
    if len(non_empty) <= 1:
        return 0.0
    uniq = len(set(non_empty))
    return max(0.0, 1.0 - uniq / len(non_empty))


def citation_relevance_proxy(payload: Dict[str, object]) -> float:
    ev = payload.get("inspiring_evidence", [])
    if not isinstance(ev, list) or not ev:
        return 0.0
    with_quote = 0
    with_src = 0
    for item in ev:
        if not isinstance(item, dict):
            continue
        if str(item.get("quote", "")).strip():
            with_quote += 1
        if str(item.get("source_excerpt", "")) or str(item.get("text", "")):
            with_src += 1
    n = max(1, len(ev))
    return 0.5 * (with_quote / n) + 0.5 * (with_src / n)


def text_repetition_rate(payload: Dict[str, object]) -> float:
    """检测文本内部的重复率，特别是单个字段内的重复句子"""
    fields = [
        "stage_explanation",
        "thesis",
        "antithesis",
        "false_synthesis",
        "true_synthesis",
        "contradiction",
        "next_stage",
        "analysis_mode",
    ]
    total_repetition = 0.0
    total_sentences = 0
    
    for field in fields:
        text = str(payload.get(field, "")).strip()
        if not text:
            continue
        
        # 分割句子
        sentences = [s.strip() for s in text.split('。') if s.strip()]
        if len(sentences) <= 1:
            continue
        
        # 计算句子重复率
        unique_sentences = set(sentences)
        repetition = len(sentences) - len(unique_sentences)
        field_repetition_rate = repetition / len(sentences)
        
        total_repetition += field_repetition_rate
        total_sentences += len(sentences)
    
    if total_sentences == 0:
        return 0.0
    
    return total_repetition / len([f for f in fields if str(payload.get(f, "")).strip()])

