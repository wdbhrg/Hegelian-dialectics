from __future__ import annotations

import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from quality_metrics import citation_relevance_proxy, field_duplicate_rate, structure_completeness
from quality_schema import repair_analysis_payload, validate_analysis_payload


def test_repair_and_validate_payload():
    raw = {"question": "我总拖延"}
    fixed = repair_analysis_payload(raw, question="我总拖延")
    ok, errors = validate_analysis_payload(fixed)
    assert ok, f"validation failed: {errors}"
    assert len(fixed.get("steps", [])) >= 6


def test_quality_metrics_basic():
    payload = {
        "question": "q",
        "stage": "s",
        "stage_explanation": "a",
        "thesis": "b",
        "antithesis": "c",
        "false_synthesis": "d",
        "true_synthesis": "e",
        "contradiction": "f",
        "aufhebung": "g",
        "next_stage": "h",
        "steps": ["x", "y"],
        "inspiring_evidence": [{"quote": "q", "source_excerpt": "s"}],
        "analysis_mode": "ai_enhanced",
        "ai_error": "none",
    }
    assert structure_completeness(payload) > 0.95
    assert 0.0 <= field_duplicate_rate(payload) <= 1.0
    assert citation_relevance_proxy(payload) >= 0.5

