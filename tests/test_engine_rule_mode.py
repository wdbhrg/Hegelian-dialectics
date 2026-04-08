from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

import hegel_engine as eng


def test_rule_mode_regression_baseline():
    baseline_path = Path(__file__).parent / "baselines" / "analysis_rule_mode.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    q = "我知道该学习，但经常拖延，越拖越焦虑，晚上又报复性熬夜。"
    result = eng.analyze_question(q, api_key="", api_base="", model="", detail_level="standard")

    for k in baseline["required_keys"]:
        assert k in result, f"missing key: {k}"
    assert result["analysis_mode"] in baseline["allowed_modes"]
    assert isinstance(result["steps"], list)
    assert len(result["steps"]) >= int(baseline["min_steps"])
    assert str(result["stage"]).strip() != ""
    assert str(result["stage_explanation"]).strip() != ""


def test_runtime_metrics_exposed():
    q = "我总在两个极端里切换，想稳定节奏。"
    _ = eng.analyze_question(q, api_key="", api_base="", model="", detail_level="concise")
    m = eng.get_runtime_metrics()
    assert isinstance(m, dict)
    assert "counters" in m
    counters = m.get("counters", {})
    assert isinstance(counters, dict)
    assert int(counters.get("analysis_total", 0)) >= 1

