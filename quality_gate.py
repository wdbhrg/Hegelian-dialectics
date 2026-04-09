from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from quality_pipeline import run_quality_pipeline

EVAL_PATH = Path("config/eval/quality_eval.jsonl")


def run_quality_gate() -> Dict[str, object]:
    if not EVAL_PATH.exists():
        return {"cases": 0, "pass_rate": 0.0, "details": []}

    details: List[Dict[str, object]] = []
    lines = [x.strip() for x in EVAL_PATH.read_text(encoding="utf-8").splitlines() if x.strip()]
    passed = 0
    cases = 0
    for line in lines:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        q = str(row.get("question", "")).strip()
        if not q:
            continue
        cases += 1
        out = run_quality_pipeline(q)
        quality = out.get("quality", {}) if isinstance(out, dict) else {}
        sc = float(quality.get("structure_completeness", 0.0))
        dr = float(quality.get("field_duplicate_rate", 1.0))
        cr = float(quality.get("citation_relevance_proxy", 0.0))
        tr = float(quality.get("text_repetition_rate", 1.0))
        ok = (
            sc >= float(row.get("min_structure", 0.95))
            and dr <= float(row.get("max_duplicate_rate", 0.35))
            and cr >= float(row.get("min_citation_relevance", 0.4))
            and tr <= float(row.get("max_text_repetition", 0.1))
        )
        if ok:
            passed += 1
        details.append(
            {
                "question": q,
                "quality": quality,
                "pass": ok,
            }
        )
    return {
        "cases": cases,
        "passed": passed,
        "pass_rate": round((passed / cases) if cases else 0.0, 4),
        "details": details,
    }


if __name__ == "__main__":
    print(json.dumps(run_quality_gate(), ensure_ascii=False, indent=2))

