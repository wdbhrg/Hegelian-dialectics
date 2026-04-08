from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, List

DATA_DIR = Path("data")
METRICS_PATH = DATA_DIR / "metrics.json"
_LOCK = threading.Lock()
_MAX_SAMPLES = 500


def _load() -> Dict[str, object]:
    if not METRICS_PATH.exists():
        return {"counters": {}, "latencies_ms": {}, "updated_at": 0}
    try:
        data = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"counters": {}, "latencies_ms": {}, "updated_at": 0}


def _save(data: Dict[str, object]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    METRICS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def increment(name: str, value: int = 1) -> None:
    with _LOCK:
        data = _load()
        counters = data.setdefault("counters", {})
        if not isinstance(counters, dict):
            counters = {}
            data["counters"] = counters
        counters[name] = int(counters.get(name, 0)) + int(value)
        data["updated_at"] = int(time.time())
        _save(data)


def observe_latency(name: str, value_ms: float) -> None:
    with _LOCK:
        data = _load()
        lat = data.setdefault("latencies_ms", {})
        if not isinstance(lat, dict):
            lat = {}
            data["latencies_ms"] = lat
        seq = lat.setdefault(name, [])
        if not isinstance(seq, list):
            seq = []
            lat[name] = seq
        seq.append(float(value_ms))
        if len(seq) > _MAX_SAMPLES:
            del seq[: len(seq) - _MAX_SAMPLES]
        data["updated_at"] = int(time.time())
        _save(data)


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int((len(s) - 1) * p)
    return float(s[idx])


def snapshot() -> Dict[str, object]:
    with _LOCK:
        data = _load()
    counters = data.get("counters", {})
    lat = data.get("latencies_ms", {})
    out_lat = {}
    if isinstance(lat, dict):
        for name, seq in lat.items():
            if not isinstance(seq, list):
                continue
            nums = [float(x) for x in seq if isinstance(x, (int, float))]
            out_lat[name] = {
                "count": len(nums),
                "p50_ms": round(percentile(nums, 0.5), 2),
                "p95_ms": round(percentile(nums, 0.95), 2),
            }
    return {
        "counters": counters if isinstance(counters, dict) else {},
        "latencies": out_lat,
        "updated_at": data.get("updated_at", 0),
    }

