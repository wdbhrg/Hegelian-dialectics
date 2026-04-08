from __future__ import annotations

from typing import Dict, List, TypedDict

from quality_cache import get_json, make_key, set_json
from quality_llm import generate_analysis_with_router
from quality_metrics import citation_relevance_proxy, field_duplicate_rate, structure_completeness
from quality_reranker import rerank_candidates
from quality_retriever import retrieve_candidates
from quality_schema import repair_analysis_payload, validate_analysis_payload


class QualityState(TypedDict, total=False):
    question: str
    cache_key: str
    cache_hit: bool
    candidates: List[Dict[str, str]]
    reranked: List[Dict[str, str]]
    raw_output: Dict[str, object]
    final_output: Dict[str, object]
    validation_errors: List[str]
    quality: Dict[str, float]


def run_quality_pipeline(question: str, model_hint: str = "") -> Dict[str, object]:
    """
    LangGraph-style quality-first pipeline:
    retrieve -> rerank -> generate -> validate -> repair -> score
    """
    state: QualityState = {"question": question.strip()}
    state["cache_key"] = make_key(state["question"], model_hint)
    cached = get_json(state["cache_key"])
    if isinstance(cached, dict):
        cached["cache_hit"] = True
        return cached

    # Try real langgraph runtime if installed
    try:
        from langgraph.graph import END, StateGraph  # type: ignore

        graph = StateGraph(QualityState)

        def n_retrieve(s: QualityState) -> QualityState:
            s["candidates"] = retrieve_candidates(s["question"], top_k=10)
            return s

        def n_rerank(s: QualityState) -> QualityState:
            s["reranked"] = rerank_candidates(s["question"], s.get("candidates", []), top_k=6)
            return s

        def n_generate(s: QualityState) -> QualityState:
            s["raw_output"] = generate_analysis_with_router(s["question"], s.get("reranked", []))
            return s

        def n_validate(s: QualityState) -> QualityState:
            ok, errors = validate_analysis_payload(s.get("raw_output", {}))
            s["validation_errors"] = errors
            if ok:
                s["final_output"] = dict(s.get("raw_output", {}))
            else:
                s["final_output"] = repair_analysis_payload(s.get("raw_output", {}), question=s["question"])
            out = s["final_output"]
            s["quality"] = {
                "structure_completeness": round(structure_completeness(out), 4),
                "field_duplicate_rate": round(field_duplicate_rate(out), 4),
                "citation_relevance_proxy": round(citation_relevance_proxy(out), 4),
            }
            return s

        graph.add_node("retrieve", n_retrieve)
        graph.add_node("rerank", n_rerank)
        graph.add_node("generate", n_generate)
        graph.add_node("validate", n_validate)
        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "rerank")
        graph.add_edge("rerank", "generate")
        graph.add_edge("generate", "validate")
        graph.add_edge("validate", END)
        app = graph.compile()
        state = app.invoke(state)
    except Exception:
        # Sequential fallback with same semantics
        state["candidates"] = retrieve_candidates(state["question"], top_k=10)
        state["reranked"] = rerank_candidates(state["question"], state.get("candidates", []), top_k=6)
        state["raw_output"] = generate_analysis_with_router(state["question"], state.get("reranked", []))
        ok, errors = validate_analysis_payload(state.get("raw_output", {}))
        state["validation_errors"] = errors
        if ok:
            state["final_output"] = dict(state.get("raw_output", {}))
        else:
            state["final_output"] = repair_analysis_payload(state.get("raw_output", {}), question=state["question"])
        out = state["final_output"]
        state["quality"] = {
            "structure_completeness": round(structure_completeness(out), 4),
            "field_duplicate_rate": round(field_duplicate_rate(out), 4),
            "citation_relevance_proxy": round(citation_relevance_proxy(out), 4),
        }

    result = dict(state.get("final_output", {}))
    result["quality"] = state.get("quality", {})
    result["validation_errors"] = state.get("validation_errors", [])
    result["cache_hit"] = False
    set_json(state["cache_key"], result)
    return result

