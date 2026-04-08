from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, Optional

_MEM: Dict[str, str] = {}
REDIS_URL = os.environ.get("HEGEL_REDIS_URL", "redis://localhost:6379/0").strip()
PREFIX = "hegel:quality:"
TTL_S = int(os.environ.get("HEGEL_CACHE_TTL_S", "900"))


def make_key(question: str, model: str = "") -> str:
    raw = f"{question.strip()}##{model.strip()}"
    return PREFIX + hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def get_json(key: str) -> Optional[Dict[str, object]]:
    # redis first
    try:
        import redis  # type: ignore

        r = redis.from_url(REDIS_URL, decode_responses=True)
        s = r.get(key)
        if s:
            return json.loads(s)
    except Exception:
        pass
    # memory fallback
    s2 = _MEM.get(key)
    if not s2:
        return None
    try:
        return json.loads(s2)
    except Exception:
        return None


def set_json(key: str, value: Dict[str, object]) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    try:
        import redis  # type: ignore

        r = redis.from_url(REDIS_URL, decode_responses=True)
        r.setex(key, max(60, TTL_S), payload)
        return
    except Exception:
        pass
    _MEM[key] = payload

