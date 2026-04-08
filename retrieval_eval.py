from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from knowledge_base import search_chunks

EVAL_PATH = Path("config/eval/retrieval_eval.jsonl")


def run_offline_retrieval_eval(top_k: int = 5) -> Dict[str, object]:
    if not EVAL_PATH.exists():
        return {"cases": 0, "recall_at_k": 0.0, "details": []}
    lines = [x.strip() for x in EVAL_PATH.read_text(encoding="utf-8").splitlines() if x.strip()]
    cases = 0
    hit_cases = 0
    details: List[Dict[str, object]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        query = str(row.get("query", "")).strip()
        expected = [str(x) for x in row.get("expected_keywords", []) if str(x).strip()]
        min_hits = int(row.get("min_hits", 1))
        if not query:
            continue
        cases += 1
        chunks = search_chunks(query, top_k=top_k)
        text = "\n".join(str(c.get("text", "")) for c in chunks)
        matched = sum(1 for kw in expected if kw in text)
        ok = matched >= min_hits
        if ok:
            hit_cases += 1
        details.append(
            {
                "query": query,
                "expected_keywords": expected,
                "matched": matched,
                "min_hits": min_hits,
                "pass": ok,
            }
        )
    recall = (hit_cases / cases) if cases > 0 else 0.0
    return {"cases": cases, "recall_at_k": round(recall, 4), "details": details}


if __name__ == "__main__":
    print(json.dumps(run_offline_retrieval_eval(), ensure_ascii=False, indent=2))

