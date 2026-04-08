from __future__ import annotations

import json
import os
from typing import Dict, List

import hegel_engine

DEFAULT_MODEL = os.environ.get("HEGEL_LITELLM_MODEL", "openai/gpt-4o-mini").strip()
LITELLM_BASE = os.environ.get("HEGEL_LITELLM_BASE_URL", "").strip()
LITELLM_KEY = os.environ.get("HEGEL_LITELLM_API_KEY", "").strip()


def _build_quality_prompt(question: str, reranked: List[Dict[str, str]]) -> str:
    chunks = []
    for i, c in enumerate(reranked[:5], start=1):
        chunks.append(f"[{i}] {c.get('chunk_id','')} {c.get('doc_path','')}\n{c.get('text','')}")
    joined = "\n\n".join(chunks)
    return (
        "你是高质量黑格尔辩证分析助手。只输出JSON对象。\n"
        f"问题：{question}\n"
        f"证据片段：\n{joined}\n"
        "必须输出字段：question,stage,stage_explanation,thesis,antithesis,false_synthesis,true_synthesis,"
        "contradiction,aufhebung,next_stage,steps,inspiring_evidence,analysis_mode,ai_error。\n"
        "steps至少6条。inspiring_evidence每条包含chunk_id/doc_path/insight/quote/source_excerpt。\n"
    )


def generate_analysis_with_router(question: str, reranked: List[Dict[str, str]]) -> Dict[str, object]:
    prompt = _build_quality_prompt(question, reranked)
    # Try LiteLLM first
    try:
        from litellm import completion  # type: ignore

        kwargs = {
            "model": DEFAULT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 1400,
        }
        if LITELLM_BASE:
            kwargs["api_base"] = LITELLM_BASE
        if LITELLM_KEY:
            kwargs["api_key"] = LITELLM_KEY
        resp = completion(**kwargs)
        content = resp.choices[0].message.content
        parsed = json.loads(content) if isinstance(content, str) else {}
        if isinstance(parsed, dict):
            parsed.setdefault("analysis_mode", "ai_enhanced")
            parsed.setdefault("ai_error", "")
            return parsed
    except Exception:
        pass

    # Fallback to existing stable engine
    return hegel_engine.analyze_question(
        user_question=question,
        api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        api_base=os.environ.get("OPENAI_API_BASE", "").strip(),
        model=os.environ.get("OPENAI_MODEL", "").strip(),
        prefetched_candidates=reranked,
        detail_level="standard",
    )

