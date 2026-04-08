from __future__ import annotations

import json
from typing import Dict, List, Tuple

REQUIRED_KEYS = [
    "question",
    "stage",
    "stage_explanation",
    "thesis",
    "antithesis",
    "false_synthesis",
    "true_synthesis",
    "contradiction",
    "aufhebung",
    "next_stage",
    "steps",
    "inspiring_evidence",
    "analysis_mode",
    "ai_error",
]

ANALYSIS_JSON_SCHEMA: Dict[str, object] = {
    "type": "object",
    "required": REQUIRED_KEYS,
    "properties": {
        "question": {"type": "string"},
        "stage": {"type": "string"},
        "stage_explanation": {"type": "string"},
        "thesis": {"type": "string"},
        "antithesis": {"type": "string"},
        "false_synthesis": {"type": "string"},
        "true_synthesis": {"type": "string"},
        "contradiction": {"type": "string"},
        "aufhebung": {"type": "string"},
        "next_stage": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
        "inspiring_evidence": {"type": "array"},
        "analysis_mode": {"type": "string"},
        "ai_error": {"type": "string"},
    },
}


def validate_analysis_payload(payload: Dict[str, object]) -> Tuple[bool, List[str]]:
    try:
        from jsonschema import Draft7Validator  # type: ignore

        validator = Draft7Validator(ANALYSIS_JSON_SCHEMA)
        errors = [f"{'.'.join([str(x) for x in e.path])}: {e.message}" for e in validator.iter_errors(payload)]
        return (len(errors) == 0, errors)
    except Exception:
        # Fallback: lightweight checks without dependency
        errors: List[str] = []
        if not isinstance(payload, dict):
            return False, ["payload is not object"]
        for k in REQUIRED_KEYS:
            if k not in payload:
                errors.append(f"missing key: {k}")
        if not isinstance(payload.get("steps", []), list):
            errors.append("steps is not list")
        if not isinstance(payload.get("inspiring_evidence", []), list):
            errors.append("inspiring_evidence is not list")
        return (len(errors) == 0, errors)


def repair_analysis_payload(payload: Dict[str, object], *, question: str = "") -> Dict[str, object]:
    base = dict(payload or {})
    base.setdefault("question", question)
    base.setdefault("stage", "")
    base.setdefault("stage_explanation", "")
    base.setdefault("thesis", "")
    base.setdefault("antithesis", "")
    base.setdefault("false_synthesis", "")
    base.setdefault("true_synthesis", "")
    base.setdefault("contradiction", "")
    base.setdefault("aufhebung", "")
    base.setdefault("next_stage", "")
    base.setdefault("steps", [])
    base.setdefault("inspiring_evidence", [])
    base.setdefault("analysis_mode", "ai_enhanced")
    base.setdefault("ai_error", "")

    # type repairs
    if not isinstance(base["steps"], list):
        base["steps"] = [str(base["steps"])]
    base["steps"] = [str(x) for x in base["steps"] if str(x).strip()]
    if len(base["steps"]) < 6:
        booster = [
            "先明确今天唯一要解决的一件事",
            "把任务拆成15-20分钟最小动作",
            "完成后记录结果并复盘",
            "若卡住，降低难度继续做",
            "当天结束前做下一步预设",
            "连续执行三天后再升级强度",
        ]
        base["steps"].extend(booster[: 6 - len(base["steps"])])

    if not isinstance(base["inspiring_evidence"], list):
        base["inspiring_evidence"] = []
    for k in [x for x in REQUIRED_KEYS if x not in ("steps", "inspiring_evidence")]:
        base[k] = str(base.get(k, ""))
    return base


def to_json_text(payload: Dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

