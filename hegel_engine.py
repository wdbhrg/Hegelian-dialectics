from __future__ import annotations

import json
import os
import time
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Generator, List, Optional

import requests

from env_bootstrap import bootstrap_env
from knowledge_base import search_chunks
from telemetry import increment as metric_inc, observe_latency as metric_observe, snapshot as telemetry_snapshot
from hegel_stages import STAGES, HegelStage
_log_retrieval_quality = None

bootstrap_env()


def _env_int(key: str, default: int, *, min_v: Optional[int] = None, max_v: Optional[int] = None) -> int:
    try:
        raw = os.environ.get(key, "").strip()
        v = int(raw) if raw else default
        if min_v is not None:
            v = max(min_v, v)
        if max_v is not None:
            v = min(max_v, v)
        return v
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


# 快速分析：压缩输入/输出 token；HTTP 等待时间与模型/线路有关（方舟常需数十秒以上）
FAST_SEARCH_TOP_K = _env_int("HEGEL_SEARCH_TOP_K", 10, min_v=4, max_v=24)
FAST_MAX_CHUNKS = _env_int("HEGEL_FAST_MAX_CHUNKS", 3, min_v=2, max_v=6)
FAST_CHARS_PER_CHUNK = _env_int("HEGEL_FAST_CHARS_PER_CHUNK", 180, min_v=100, max_v=500)
FAST_TOTAL_CHARS = _env_int("HEGEL_FAST_TOTAL_CHARS", 680, min_v=300, max_v=2200)
FAST_RETRY_CHUNKS = 2
FAST_RETRY_CHARS = 120
FAST_RETRY_TOTAL = 320
# 可通过环境变量覆盖，例如：set HEGEL_LLM_READ_TIMEOUT=180
LLM_CONNECT_TIMEOUT_S = _env_int("HEGEL_LLM_CONNECT_TIMEOUT", 15, min_v=5, max_v=120)
LLM_READ_TIMEOUT_S = _env_int("HEGEL_LLM_READ_TIMEOUT", 120, min_v=30, max_v=600)
LLM_MAX_RETRIES = _env_int("HEGEL_LLM_MAX_RETRIES", 2, min_v=0, max_v=8)
LLM_RETRY_BACKOFF_S = _env_int("HEGEL_LLM_RETRY_BACKOFF", 2, min_v=1, max_v=20)
LLM_MAX_TOKENS = _env_int("HEGEL_LLM_MAX_TOKENS", 1600, min_v=256, max_v=8192)
EVIDENCE_TARGET_COUNT = _env_int("HEGEL_EVIDENCE_COUNT", 6, min_v=2, max_v=10)
ENABLE_STREAM_PRIMARY = _env_bool("HEGEL_STREAM_PRIMARY", False)
LIGHT_MODEL = os.environ.get("HEGEL_LIGHT_MODEL", "").strip()
ENABLE_LIGHT_ROUTER = os.environ.get("HEGEL_ENABLE_LIGHT_ROUTER", "1").strip().lower() in {"1", "true", "yes"}
ENABLE_KV_CACHE_HINT = os.environ.get("HEGEL_KV_CACHE_ENABLED", "0").strip().lower() in {"1", "true", "yes"}

DATA_DIR = Path("data")
ANALYSIS_CACHE_PATH = DATA_DIR / "analysis_cache.json"
ANALYSIS_CACHE_LIMIT = _env_int("HEGEL_ANALYSIS_CACHE_LIMIT", 80, min_v=0, max_v=400)
CACHE_SCHEMA_VERSION = "v4_balanced_nonrepeat"
ENGINE_BUILD = "2026-04-07-v3-ultra-long"
_ANALYSIS_CACHE: Optional[Dict[str, Dict[str, object]]] = None


def _load_analysis_cache() -> Dict[str, Dict[str, object]]:
    global _ANALYSIS_CACHE
    if _ANALYSIS_CACHE is not None:
        return _ANALYSIS_CACHE
    DATA_DIR.mkdir(exist_ok=True)
    if not ANALYSIS_CACHE_PATH.exists():
        _ANALYSIS_CACHE = {}
        return _ANALYSIS_CACHE
    try:
        raw = json.loads(ANALYSIS_CACHE_PATH.read_text(encoding="utf-8"))
        _ANALYSIS_CACHE = raw if isinstance(raw, dict) else {}
    except Exception:
        _ANALYSIS_CACHE = {}
    return _ANALYSIS_CACHE


def _save_analysis_cache(cache: Dict[str, Dict[str, object]]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    try:
        ANALYSIS_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def clear_analysis_cache() -> None:
    global _ANALYSIS_CACHE
    _ANALYSIS_CACHE = {}
    try:
        if ANALYSIS_CACHE_PATH.exists():
            ANALYSIS_CACHE_PATH.unlink()
    except Exception:
        pass


def get_runtime_metrics() -> Dict[str, object]:
    """Expose runtime metrics for UI/ops."""
    return telemetry_snapshot()


def _make_cache_key(question: str, detail_level: str, model: str, candidate: List[Dict[str, str]]) -> str:
    ids = "|".join(str(c.get("chunk_id", "")) for c in candidate[:4])
    raw = f"{CACHE_SCHEMA_VERSION}##{question.strip()}##{detail_level}##{model}##{ids}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def _repair_mojibake(text: str) -> str:
    suspicious = "ÃÂÆÐÑØÙàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ"
    score = sum(1 for ch in text if ch in suspicious)
    if score < max(8, len(text) // 120):
        return text
    try:
        fixed = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        return text
    cjk_old = len(re.findall(r"[\u4e00-\u9fff]", text))
    cjk_new = len(re.findall(r"[\u4e00-\u9fff]", fixed))
    return fixed if cjk_new > cjk_old else text


def _repair_ai_payload(obj: object) -> object:
    if isinstance(obj, str):
        return _repair_mojibake(obj)
    if isinstance(obj, list):
        return [_repair_ai_payload(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _repair_ai_payload(v) for k, v in obj.items()}
    return obj


@dataclass
class HegelStage:
    name: str
    thesis: str
    antithesis: str
    contradiction_hint: str
    aufhebung: str
    next_stage: str
    plan_steps: List[str]
    keywords: List[str]


STAGES: List[HegelStage] = [
    HegelStage(
        name="存在论-定在与质",
        thesis="先把问题看作一个直接给定的事实（定在）。",
        antithesis="该事实依赖其性质和边界（质），不是孤立之物。",
        contradiction_hint="你把“事实本身”与“维持其本性的条件”割裂了。",
        aufhebung="把问题转为边界管理：保留核心质，调整非核心条件。",
        next_stage="有限性与应当",
        plan_steps=["定义核心质", "标出可变条件", "先做一次低风险验证"],
        keywords=["定位", "边界", "失控", "定义不清"],
    ),
    HegelStage(
        name="存在论-有限与无限",
        thesis="你正在经验限制（有限）。",
        antithesis="你同时追求突破（应当/无限）。",
        contradiction_hint="把限制看成纯障碍，没有看到其发展功能。",
        aufhebung="把限制转化为训练条件，建立阶段性超越循环。",
        next_stage="一与多",
        plan_steps=["列3个限制", "写每个限制能训练的能力", "拆成7/30/90天目标"],
        keywords=["瓶颈", "突破", "上限", "卡住"],
    ),
    HegelStage(
        name="量-质-尺度",
        thesis="你通过增加投入推进变化（量变）。",
        antithesis="超过阈值会导致性质反转（质变）。",
        contradiction_hint="持续加码却没有定义临界尺度。",
        aufhebung="建立尺度表：健康区间、预警区间、危险区间。",
        next_stage="本质与现象",
        plan_steps=["选3个指标", "定义阈值", "预警即换挡"],
        keywords=["过度", "拖延", "焦虑", "崩溃", "量变", "质变", "临界点"],
    ),
    HegelStage(
        name="本质与现象",
        thesis="你先看到反复出现的表面现象。",
        antithesis="现象背后有可复现的结构根据。",
        contradiction_hint="只描述结果，未定位结构因。",
        aufhebung="建立“现象-根据”双栏诊断并只改一个可控根据。",
        next_stage="根据与条件到实存",
        plan_steps=["记3个重复现象", "每个写2个根据", "只改1个并观察7天"],
        keywords=["总是", "反复", "根因", "为什么我总"],
    ),
    HegelStage(
        name="根据与条件到实存",
        thesis="你有目标根据（为什么做）。",
        antithesis="缺外在条件就无法落地。",
        contradiction_hint="把“想做”与“能做”割裂。",
        aufhebung="把目标改写为：根据+条件+触发器。",
        next_stage="现实中的偶然与必然",
        plan_steps=["写一句根据", "列必要条件", "设置触发器并执行最小动作"],
        keywords=["执行力", "坚持", "行动不了", "计划落空"],
    ),
]


def detect_stage(user_question: str) -> HegelStage:
    text = user_question.lower()
    best = STAGES[0]
    best_score = -1
    for stage in STAGES:
        score = sum(1 for kw in stage.keywords if kw in user_question or kw.lower() in text)
        if score > best_score:
            best = stage
            best_score = score
    return best


def _build_prompt(
    user_question: str,
    candidate_chunks: List[Dict[str, str]],
    detail_level: str = "standard",
) -> str:
    """短输出提示：模型先给紧凑草稿，再由本地扩写到档位长度。"""
    lvl = (detail_level or "standard").lower()
    if lvl == "concise":
        lens = {
            "stage_explain": "140-220字",
            "thesis": "80-120字",
            "antithesis": "80-120字",
            "false_syn": "100-140字",
            "true_syn": "100-140字",
            "contradiction": "100-140字",
            "next_stage": "70-110字",
            "quote": "120-180字",
        }
    elif lvl == "detailed":
        lens = {
            "stage_explain": "260-420字",
            "thesis": "120-180字",
            "antithesis": "120-180字",
            "false_syn": "150-220字",
            "true_syn": "150-220字",
            "contradiction": "150-220字",
            "next_stage": "110-170字",
            "quote": "180-280字",
        }
    else:
        lens = {
            "stage_explain": "180-300字",
            "thesis": "100-150字",
            "antithesis": "100-150字",
            "false_syn": "130-190字",
            "true_syn": "130-190字",
            "contradiction": "130-190字",
            "next_stage": "90-140字",
            "quote": "150-240字",
        }
    chunk_text = []
    for i, ch in enumerate(candidate_chunks, start=1):
        chunk_text.append(f"[{i}] id={ch['chunk_id']} src={ch['doc_path']}\n{ch['text']}")
    joined = "\n\n".join(chunk_text)
    return f"""你是黑格尔逻辑学生活问题分析助手。只输出一个合法 JSON 对象，不要 markdown，不要前后说明。

用户问题：
{user_question}

候选片段：
{joined}

输出 JSON 结构（字段齐全；请精炼，不要长篇）：
{{
  "inspiring_evidence": [
    {{"chunk_id":"与候选一致", "doc_path":"与候选一致", "insight":"为什么有启发（2-4句）", "quote":"通俗化重构，紧扣用户问题，{lens['quote']}"}},
    {{"chunk_id":"与候选一致", "doc_path":"与候选一致", "insight":"一句", "quote":"同上"}}
  ],
  "stage_override": "",
  "stage_explain_refine": "所处逻辑环节的通俗讲解（必须结合用户问题，按正题-反题-矛盾-扬弃展开），{lens['stage_explain']}",
  "thesis_refine": "正题，{lens['thesis']}",
  "antithesis_refine": "反题，{lens['antithesis']}",
  "false_synthesis_refine": "虚假合题，{lens['false_syn']}",
  "true_synthesis_refine": "真正合题，{lens['true_syn']}",
  "contradiction_refine": "核心矛盾，{lens['contradiction']}",
  "next_stage_refine": "下一环节，{lens['next_stage']}",
  "steps_refine": [
    "可执行一步",
    "可执行一步",
    "可执行一步",
    "可执行一步"
  ]
}}

规则：
1) inspiring_evidence 先给2-3条最相关内容即可（系统会自动补齐到展示数量）；quote 须结合用户问题与片段。
2) 每个字段都要有信息量，但尽量短、直接、可解析。
3) steps_refine 先给4-6步高质量草稿即可（系统会自动补齐到10步），每步20字以上。
4) 文风要通俗、有人味，像在和真实用户对话，不要“自言自语式”分析。
5) thesis_refine / antithesis_refine / false_synthesis_refine / true_synthesis_refine / contradiction_refine / next_stage_refine 中，禁止原样复述用户问题原句，必须转述表达。
6) stage_explain_refine 不能一句话了事，必须把“为什么是这个环节”讲清楚，并给出缓解当前冲突的扬弃方向。
""".strip()


def _pick_runtime_model(base_model: str, user_question: str) -> str:
    if not ENABLE_LIGHT_ROUTER or not LIGHT_MODEL:
        return base_model
    q = user_question.lower()
    summarize_signals = ("总结", "摘要", "概括", "提炼", "归纳", "summary", "summarize")
    if any(s in q for s in summarize_signals):
        return LIGHT_MODEL
    return base_model


def _truncate_chunks(
    chunks: List[Dict[str, str]],
    max_chunks: int,
    max_chars_per_chunk: int,
    max_total_chars: int,
) -> List[Dict[str, str]]:
    selected: List[Dict[str, str]] = []
    total = 0
    for ch in chunks[:max_chunks]:
        text = str(ch.get("text", ""))
        if len(text) > max_chars_per_chunk:
            text = text[:max_chars_per_chunk]
        if total + len(text) > max_total_chars:
            break
        item = dict(ch)
        item["text"] = text
        selected.append(item)
        total += len(text)
    return selected


def _normalize_inspiring_evidence_length(
    evidence: List[Dict[str, object]],
    candidate_chunks: List[Dict[str, str]],
    user_question: str = "",
    detail_level: str = "standard",
    min_len: int = 70,
) -> List[Dict[str, object]]:
    def _full_paragraph_excerpt(text: str, max_paragraphs: int = 2) -> str:
        paras = [p.strip() for p in text.split("\n") if p.strip()]
        if not paras:
            return text.strip()
        excerpt = "\n\n".join(paras[:max_paragraphs]).strip()

        # Repair broken starts such as "未知a，..." / sentence continuation fragments.
        if excerpt.startswith("未知") or excerpt.startswith("，") or excerpt.startswith(","):
            for sep in ("。", "！", "？", "；"):
                idx = excerpt.find(sep)
                if 0 <= idx < 140:
                    excerpt = excerpt[idx + 1 :].strip()
                    break

        # If first sentence is very short fragment, drop it.
        first_stop = min(
            [i for i in [excerpt.find("。"), excerpt.find("！"), excerpt.find("？"), excerpt.find("；")] if i != -1],
            default=-1,
        )
        if 0 <= first_stop < 25:
            excerpt = excerpt[first_stop + 1 :].strip()

        # Ensure ending on sentence boundary to avoid trailing half sentence.
        last_stop = max(excerpt.rfind("。"), excerpt.rfind("！"), excerpt.rfind("？"), excerpt.rfind("；"))
        if last_stop > 0:
            excerpt = excerpt[: last_stop + 1].strip()

        return excerpt

    def _tokenize_short(q: str) -> List[str]:
        ql = q.lower().strip()
        latin = re.findall(r"[a-z0-9_]+", ql)
        han = re.sub(r"[^\u4e00-\u9fff]", "", ql)
        han_bg = [han[i : i + 2] for i in range(max(0, len(han) - 1))]
        terms = [t for t in (latin + han_bg) if t]
        seen = set()
        out: List[str] = []
        for t in terms:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out[:18]

    def _best_short_excerpt(text: str, q: str, max_chars: int = 900) -> str:
        # 选最贴切的一小段（长摘录版）：以最相关句为中心，向前后扩展，避免整段搬运。
        raw = _full_paragraph_excerpt(text, max_paragraphs=6)
        if not raw:
            return ""
        sents = [s.strip() for s in re.split(r"(?<=[。！？；])", raw) if s.strip()]
        if not sents:
            sents = [raw.strip()]
        terms = _tokenize_short(q)

        def _score(s: str) -> int:
            low = s.lower()
            score = 0
            for t in terms:
                if t in low:
                    score += 2 if len(t) == 2 else 1
            return score

        # 找到最相关的锚点句
        best_idx = max(range(len(sents)), key=lambda i: (_score(sents[i]), -abs(len(sents[i]) - 60)))
        left = best_idx
        right = best_idx
        picked = sents[best_idx]

        # 以锚点向两侧扩展，优先保证连贯上下文，直到达到目标长度
        while len(picked) < max_chars:
            moved = False
            if left > 0:
                cand = (sents[left - 1] + " " + picked).strip()
                if len(cand) <= max_chars:
                    picked = cand
                    left -= 1
                    moved = True
            if right < len(sents) - 1:
                cand = (picked + " " + sents[right + 1]).strip()
                if len(cand) <= max_chars:
                    picked = cand
                    right += 1
                    moved = True
            if not moved:
                break
        return picked

    def _shorten_quote(text: str, q: str, max_chars: int = 560) -> str:
        # 保留重点且保证内容厚度：优先相关句，拼接到目标长度上限。
        raw = str(text or "").strip()
        if not raw:
            return ""
        sents = [s.strip() for s in re.split(r"(?<=[。！？；])", raw) if s.strip()]
        if not sents:
            sents = [raw]
        terms = _tokenize_short(q)
        def _score(s: str) -> int:
            low = s.lower()
            score = 0
            for t in terms:
                if t in low:
                    score += 2 if len(t) == 2 else 1
            return score
        ranked = sorted(sents, key=lambda s: (_score(s), -abs(len(s) - 64)), reverse=True)
        out_parts: List[str] = []
        total = 0
        for s in ranked:
            if total + len(s) + 1 > max_chars:
                continue
            out_parts.append(s)
            total += len(s) + 1
            if total >= int(max_chars * 0.8):
                break
        out = " ".join(out_parts).strip() or ranked[0]
        if len(out) <= max_chars:
            return out
        cut = out[:max_chars]
        last_stop = max(cut.rfind("，"), cut.rfind("。"), cut.rfind("；"), cut.rfind("："))
        return (cut[: last_stop + 1] if last_stop >= 20 else cut).strip()

    by_chunk = {c.get("chunk_id", ""): c for c in candidate_chunks}
    level_map = {
        "concise": {"quote_chars": 520, "excerpt_chars": 700, "quote_min": 320, "insight_min": 120},
        "standard": {"quote_chars": 900, "excerpt_chars": 900, "quote_min": 560, "insight_min": 200},
        "detailed": {"quote_chars": 1400, "excerpt_chars": 1200, "quote_min": 900, "insight_min": 320},
    }
    cfg = level_map.get(detail_level, level_map["standard"])
    normalized: List[Dict[str, object]] = []
    for item in evidence:
        row = dict(item)
        quote = str(row.get("quote", "")).strip()
        chunk_id = str(row.get("chunk_id", ""))
        doc_path = str(row.get("doc_path", ""))

        matched = by_chunk.get(chunk_id)
        if not matched and doc_path:
            for c in candidate_chunks:
                if str(c.get("doc_path", "")) == doc_path:
                    matched = c
                    row["chunk_id"] = c.get("chunk_id", row.get("chunk_id", ""))
                    break
        if not matched and candidate_chunks:
            matched = candidate_chunks[0]
            row["chunk_id"] = matched.get("chunk_id", row.get("chunk_id", ""))
            row["doc_path"] = matched.get("doc_path", row.get("doc_path", ""))

        raw = str(matched.get("text", "")) if matched else ""
        full_para = _full_paragraph_excerpt(raw, max_paragraphs=2) if raw else ""
        if len(quote) < min_len:
            if full_para:
                row["quote"] = "通俗化重构参考：" + _shorten_quote(
                    full_para, user_question, max_chars=int(cfg["quote_chars"])
                )
        else:
            row["quote"] = _shorten_quote(quote, user_question, max_chars=int(cfg["quote_chars"]))
        row["insight"] = _expand_to_min_len(
            str(row.get("insight", "")),
            int(cfg["insight_min"]),
            "启发点",
            user_question,
        )
        row["quote"] = _expand_to_min_len(
            str(row.get("quote", "")),
            int(cfg["quote_min"]),
            "通俗化重构参考内容",
            user_question,
        )
        if full_para:
            row["source_excerpt"] = _best_short_excerpt(
                full_para, user_question, max_chars=int(cfg["excerpt_chars"])
            )
        normalized.append(row)
    return normalized


def _ensure_evidence_count(
    evidence: List[Dict[str, object]],
    candidate_chunks: List[Dict[str, str]],
    *,
    user_question: str,
    detail_level: str,
    target_count: int = EVIDENCE_TARGET_COUNT,
) -> List[Dict[str, object]]:
    """将证据条数补齐到目标数量，并统一做长度/语气规范。"""
    target = max(2, int(target_count))
    base: List[Dict[str, object]] = []
    used_ids: set[str] = set()

    for item in (evidence or []):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        cid = str(row.get("chunk_id", "")).strip()
        if cid:
            used_ids.add(cid)
        base.append(row)
        if len(base) >= target:
            break

    if len(base) < target:
        for ch in candidate_chunks:
            cid = str(ch.get("chunk_id", "")).strip()
            if cid and cid in used_ids:
                continue
            base.append(
                {
                    "chunk_id": cid,
                    "doc_path": str(ch.get("doc_path", "")),
                    "insight": "这段材料能补上你当前问题里容易被忽略的一环，帮助你把“触发-反应-后果”的链条看完整。",
                    "quote": "",
                }
            )
            if cid:
                used_ids.add(cid)
            if len(base) >= target:
                break

    return _normalize_inspiring_evidence_length(
        base[:target],
        candidate_chunks,
        user_question=user_question,
        detail_level=detail_level,
    )


def _call_llm_json(
    prompt: str,
    api_key: str,
    api_base: str,
    model: str,
    timeout_s: int = LLM_READ_TIMEOUT_S,
    max_retries: int = LLM_MAX_RETRIES,
    max_tokens: int = LLM_MAX_TOKENS,
) -> Optional[Dict[str, object]]:
    _t_req = time.perf_counter()
    runtime_model = _pick_runtime_model(model, prompt)
    base = api_base.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        url = base
    else:
        url = base + "/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        # 避免部分网关在 keep-alive 复用连接时触发 TLS EOF 中断
        "Connection": "close",
    }
    # Cherry Studio style OpenAI-compatible payload
    payload = {
        "model": runtime_model,
        "temperature": 0.25,
        "stream": False,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": "只输出合法 JSON，无其他文字。"},
            {"role": "user", "content": prompt},
        ],
    }
    if ENABLE_KV_CACHE_HINT:
        payload["prompt_cache_key"] = hashlib.sha1(prompt.encode("utf-8", errors="ignore")).hexdigest()[:32]
        payload["kv_cache"] = True
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=(LLM_CONNECT_TIMEOUT_S, timeout_s),
            )
            break
        except (
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.SSLError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        ) as ex:
            last_error = ex
            if attempt >= max_retries:
                metric_inc("llm_request_errors")
                raise RuntimeError(f"Request timeout after retries: {ex}") from ex
            time.sleep(float(LLM_RETRY_BACKOFF_S) * (attempt + 1))
    else:
        if last_error:
            raise RuntimeError(f"Request failed: {last_error}") from last_error
        raise RuntimeError("Request failed with unknown timeout error.")

    if resp.status_code >= 400:
        metric_inc("llm_http_errors")
        try:
            err = resp.json()
        except Exception:
            err = resp.text
        raise RuntimeError(f"HTTP {resp.status_code}: {err}")

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"Missing choices in response: {data}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    # Some providers return only reasoning content or alternative field names
    if content is None:
        content = message.get("reasoning_content") or choices[0].get("text") or data.get("output_text")
    if content is None:
        raise RuntimeError(f"Missing message content in response: {data}")
    if isinstance(content, list):
        # OpenAI-compatible multimodal content array: [{"type":"text","text":"..."}]
        content = "".join(
            (
                part.get("text", "")
                if isinstance(part, dict)
                else str(part)
            )
            for part in content
        )
    content = str(content).strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
    parsed = _try_parse_json_object(content)
    metric_observe("llm_request_ms", (time.perf_counter() - _t_req) * 1000.0)
    if parsed is None:
        metric_inc("llm_parse_failures")
    else:
        metric_inc("llm_parse_success")
    return parsed


def _try_parse_json_object(content: str) -> Optional[Dict[str, object]]:
    """
    尝试从模型文本中解析 JSON 对象，并对常见格式问题做轻量修复：
    - 尾逗号
    - 对象字段之间漏逗号（上一字段以 ] / } / " 结束）
    """
    text = str(content or "").strip()
    if not text:
        return None

    candidates: List[str] = []
    candidates.append(text)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    def _variants(s: str) -> List[str]:
        s1 = s
        # 去尾逗号: {"a":1,} / [1,2,]
        s2 = re.sub(r",\s*([}\]])", r"\1", s1)
        # 对象字段缺逗号: ..."}  "next":...
        s3 = re.sub(r'([}\]"])\s*(\n\s*"[^"\n]+"\s*:)', r"\1,\2", s2)
        s4 = re.sub(r'([}\]"])\s+("([^"\n]|\\")+"\s*:)', r"\1, \2", s3)
        out = [s1, s2, s3, s4]
        uniq: List[str] = []
        seen = set()
        for x in out:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        return uniq

    for cand in candidates:
        for v in _variants(cand):
            try:
                loaded = json.loads(v)
                if isinstance(loaded, dict):
                    return _repair_ai_payload(loaded)
            except json.JSONDecodeError:
                continue
            except Exception:
                continue
    return None


def _call_llm_json_stream(
    prompt: str,
    api_key: str,
    api_base: str,
    model: str,
    timeout_s: int = LLM_READ_TIMEOUT_S,
    max_tokens: int = LLM_MAX_TOKENS,
) -> Generator[Dict[str, object], None, Dict[str, object]]:
    runtime_model = _pick_runtime_model(model, prompt)
    base = api_base.strip().rstrip("/")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "close",
    }
    payload = {
        "model": runtime_model,
        "temperature": 0.25,
        "stream": True,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": "只输出合法 JSON，无其他文字。"},
            {"role": "user", "content": prompt},
        ],
    }
    if ENABLE_KV_CACHE_HINT:
        payload["prompt_cache_key"] = hashlib.sha1(prompt.encode("utf-8", errors="ignore")).hexdigest()[:32]
        payload["kv_cache"] = True
    with requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=(LLM_CONNECT_TIMEOUT_S, timeout_s),
        stream=True,
    ) as resp:
        resp.encoding = "utf-8"
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            raise RuntimeError(f"HTTP {resp.status_code}: {err}")

        pieces: List[str] = []
        for raw in resp.iter_lines(decode_unicode=False):
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                evt = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = evt.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            chunk = delta.get("content")
            if isinstance(chunk, list):
                chunk = "".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in chunk
                )
            chunk = str(chunk or "")
            if chunk:
                pieces.append(chunk)
                yield {"type": "delta", "text": chunk}

        content = "".join(pieces).strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()
        parsed: Optional[Dict[str, object]] = _try_parse_json_object(content)
        return parsed or {}


def _pick_refine_str(ai: Dict[str, object], key: str, fallback: str) -> str:
    """从 AI JSON 取字符串字段；缺省或非字符串时用 fallback，绝不触发 KeyError。"""
    v = ai.get(key)
    if isinstance(v, str) and v.strip():
        return v.strip()
    return fallback


def _expand_to_min_len(text: str, min_chars: int, label: str, context: str = "") -> str:
    """若模型输出过短，自动补全到最低字数，并保持自然连贯段落。"""
    base = re.sub(r"\s+", " ", str(text or "").strip())
    if len(base) >= min_chars:
        return base

    ctx = context[:160] if context else "用户当前处境"
    if "正题" in label:
        continuation = (
            f"围绕“正题”，先把你当下必须守住的底线摆在台面上：在{ctx}这种局面里，"
            "先稳住生存、任务与基本秩序，本身就是合理优先级。"
            "这不是保守，而是给后续改变保留行动能力。"
            "正题要回答的是“此刻最不能丢的是什么”，把这个锚点钉住后，焦虑会先下降一截，执行才有抓手。"
        )
        tail = "可先做一个最小保底动作：今天只完成一件最关键的小任务，用“先稳住”替代“全做完”。"
    elif "反题" in label:
        continuation = (
            f"围绕“反题”，要看到另一股同样真实的力量：你不是不努力，而是身体和情绪在对{ctx}发出代价信号。"
            "反题不是跟正题作对，而是在提醒“继续同样方式会失衡”。"
            "它的价值是迫使你承认边界、调整节奏，否则系统会用更激烈的方式让你停下。"
        )
        tail = "可以把反题转成一句提醒语：当出现透支征兆时，立刻降档，而不是继续硬顶。"
    elif "虚假" in label:
        continuation = (
            "“虚假的合题”通常表现为表面两边都照顾，实际两边都恶化。"
            "比如口头上说要平衡，执行上却继续透支；短期看像在前进，长期看是在透支未来。"
            "这类方案的问题不在态度，而在结构：没有改机制，只是在旧轨道上加意志。"
        )
        tail = "判断标准很简单：如果三天后更乱更累，这就是虚假合题，应立即停用。"
    elif "真正" in label:
        continuation = (
            "“真正的合题”不是折中平均，而是升级结构：把必须完成的任务和身体可承受的节奏同时纳入同一套方案。"
            "它保留了正题的现实性，也吸收了反题的边界提醒，最后形成可持续执行的路径。"
            "核心是可重复，而不是某一天爆发式表现。"
        )
        tail = "合题是否成立，看两点：任务推进是否变稳、身心负担是否下降。两者缺一不可。"
    elif "主要矛盾" in label:
        continuation = (
            "“主要矛盾”要抓的是最能牵动全局的冲突，而不是所有问题都一起解决。"
            "你现在最关键的冲突，多半是“高压目标”与“恢复能力不足”之间的剪刀差。"
            "不先处理这个，其他技巧都会被拖垮。先抓主矛盾，等于先拧对总开关。"
        )
        tail = "先把次要矛盾放一放，集中一周只改主矛盾相关动作，观察是否出现连锁改善。"
    elif "下一环节" in label:
        continuation = (
            "“下一环节”不是重新立大目标，而是把当前分析落到下一步可验证动作。"
            "它强调顺序：先做能稳定系统的小动作，再逐步加难度。"
            "只要下一环节设计得对，你会看到“可持续的小胜利”，而不是靠爆发维持。"
        )
        tail = "下一步请写成“何时-何地-做什么-做到什么程度算完成”，避免抽象口号。"
    elif "启发点" in label:
        continuation = (
            "你先别急着自责，先把最近一次失控拆开看：当时发生了什么、你脑子里冒出什么念头、接着做了什么。"
            "把这三步连起来，你就能看见自己不是“突然崩掉”，而是被一条固定链路推着走。"
            "一旦看清这条链路，你就能在第二步截断它：把“我完了”换成“我先做最小动作”。"
            "这个方法不只解决这一次，下一次类似压力来时也能复用。"
        )
        tail = "现在就写下一句个人规则：一旦压力上头，我先做5分钟最小动作，再决定要不要继续。"
    elif "通俗化重构参考内容" in label:
        continuation = (
            "说人话就是：你现在总在两个极端里来回摆——要么把自己逼到透支，要么一下子彻底放飞。"
            "问题不在你意志差，而在节奏设计错了：没有中间档。"
            "你真正需要的不是“永远完美自律”，而是给每天安排一个能完成的中间档，既推进正事，也留出恢复空间。"
            "当你连续几天都能跑在中间档上，恶性循环就会慢慢断开。"
        )
        tail = "今天就定一个中间档动作：在固定时间做25分钟正事，结束后休息10分钟，然后只加做一轮。"
    else:
        continuation = (
            f"围绕“{label}”看{ctx}，先把现状、限制和可动空间拆开，再决定先动哪里。"
            "目标不是一次解决全部问题，而是先找到最小可行改变。"
        )
        tail = "当你能持续执行小步动作时，整体局面会比“偶尔爆发一次”更快变好。"

    out = (base + " " + continuation).strip() if base else continuation
    if len(out) < min_chars:
        out = (out + " " + tail).strip()

    # 强制达标：直到满足最小字数，不再出现“看起来补了但仍不足”的情况
    boosters = [
        f"围绕“{label}”推进，关键是把大目标拆成可执行的小步骤，每天只聚焦一个动作，用结果验证方向。",
        f"在{ctx}的局面下，先建立最小可行的行动节奏，保持连续性比偶尔的爆发更重要。",
        f"把注意力放在可控制的部分，从最小的改变开始，逐步累积正向反馈。",
        f"每完成一个小目标，就记录下来，这会形成正向循环，增强你的信心和动力。",
        f"保持耐心，改变需要时间，关键是持续行动，而不是追求完美。"
    ]
    guard = 0
    booster_index = 0
    while len(out) < min_chars and guard < 20:
        out = (out + " " + boosters[booster_index % len(boosters)]).strip()
        guard += 1
        booster_index += 1

    # 给一点弹性上限，避免无限膨胀
    max_len = max(min_chars + 180, min_chars)
    return out[:max_len].strip()


def _default_stage_explanation(
    user_question: str,
    stage_name: str,
    thesis: str,
    antithesis: str,
    contradiction: str,
    next_stage: str,
) -> str:
    ctx = re.sub(r"\s+", " ", (user_question or "").strip())
    if len(ctx) > 180:
        ctx = ctx[:180].rstrip() + "..."
    return (
        f"你当前落在“{stage_name}”这个环节，说明问题已经不是“知道或不知道”，而是“哪种力量在主导你的现实”。"
        f"从辩证法看，你一边被“{thesis}”推动，另一边又被“{antithesis}”牵制，"
        "两者同时成立，所以会出现反复、拉扯、时好时坏。"
        f"这不是失败，而是阶段特征；真正需要处理的是：{contradiction}。"
        "这个环节的任务不是立刻完美，而是把冲突变成可操作顺序：先找最低成本的稳定动作，再逐步提升。"
        f"当你能连续执行并看到反馈，扬弃才会发生，系统也会自然过渡到“{next_stage}”。"
    )


def _level_minlens(detail_level: str) -> Dict[str, int]:
    lvl = (detail_level or "standard").lower()
    if lvl == "concise":
        return {
            "stage_explain": 140,
            "thesis": 80,
            "antithesis": 80,
            "false": 100,
            "true": 100,
            "contradiction": 100,
            "next": 70,
            "step": 70,
        }
    if lvl == "detailed":
        return {
            "stage_explain": 260,
            "thesis": 120,
            "antithesis": 120,
            "false": 150,
            "true": 150,
            "contradiction": 150,
            "next": 110,
            "step": 140,
        }
    return {
        "stage_explain": 180,
        "thesis": 100,
        "antithesis": 100,
        "false": 130,
        "true": 130,
        "contradiction": 130,
        "next": 110,
        "step": 100,
    }


def _strip_user_verbatim(text: str, user_question: str) -> str:
    """移除对用户问题的原句复述，保留语义并要求后续转述。"""
    out = str(text or "")
    q = re.sub(r"\s+", " ", str(user_question or "").strip())
    if not q:
        return out
    # 精确命中：直接替换为转述提示短语，避免原句出现在关键字段。
    if q in out:
        out = out.replace(q, "你的这段处境")
    # 去掉较长子串复述（长度>=14），防止“复制半句”。
    compact_q = re.sub(r"\s+", "", q)
    compact_out = re.sub(r"\s+", "", out)
    if len(compact_q) >= 28 and compact_q[:14] in compact_out:
        out = out.replace(q[:14], "这类处境")
    return out


def _ensure_min_steps(
    steps: List[str],
    *,
    min_count: int,
    user_question: str,
    stage_name: str = "",
) -> List[str]:
    out = [str(s).strip() for s in (steps or []) if str(s).strip()]
    i = len(out) + 1
    while len(out) < min_count:
        out.append(
            (
                f"第{i}步：围绕当前“{stage_name or '扬弃推进'}”做一次最小闭环——先设定今天一个可完成的小目标，"
                "执行后立刻记录结果与阻碍，再据此调整明天动作，避免只靠意志硬扛。"
            )
        )
        i += 1
    return out


def _enforce_result_minimums(result: Dict[str, object], detail_level: str, user_question: str) -> Dict[str, object]:
    minlens = _level_minlens(detail_level)
    stage_name = str(result.get("stage", "")).strip()
    stage_explain = str(result.get("stage_explanation", "")).strip()
    if not stage_explain:
        stage_explain = _default_stage_explanation(
            user_question=user_question,
            stage_name=stage_name,
            thesis=str(result.get("thesis", "")),
            antithesis=str(result.get("antithesis", "")),
            contradiction=str(result.get("contradiction", "")),
            next_stage=str(result.get("next_stage", "")),
        )
    result["stage_explanation"] = _expand_to_min_len(
        stage_explain, minlens["stage_explain"], "所处逻辑环节", user_question
    )
    result["thesis"] = _expand_to_min_len(str(result.get("thesis", "")), minlens["thesis"], "正题", user_question)
    result["antithesis"] = _expand_to_min_len(
        str(result.get("antithesis", "")), minlens["antithesis"], "反题", user_question
    )
    result["false_synthesis"] = _expand_to_min_len(
        str(result.get("false_synthesis", "")), minlens["false"], "虚假的合题", user_question
    )
    result["true_synthesis"] = _expand_to_min_len(
        str(result.get("true_synthesis", "")), minlens["true"], "真正的合题", user_question
    )
    result["contradiction"] = _expand_to_min_len(
        str(result.get("contradiction", "")), minlens["contradiction"], "主要矛盾", user_question
    )
    result["next_stage"] = _expand_to_min_len(
        str(result.get("next_stage", "")), minlens["next"], "下一环节", user_question
    )
    # 关键论证字段：禁止出现用户提问原句，统一转述。
    for k in ("thesis", "antithesis", "false_synthesis", "true_synthesis", "contradiction", "next_stage"):
        result[k] = _strip_user_verbatim(str(result.get(k, "")), user_question)
    result["stage_explanation"] = _strip_user_verbatim(str(result.get("stage_explanation", "")), user_question)

    steps = result.get("steps")
    if isinstance(steps, list):
        out_steps: List[str] = []
        padded_steps = _ensure_min_steps(
            [str(s) for s in steps],
            min_count=10,
            user_question=user_question,
            stage_name=stage_name,
        )
        for i, s in enumerate(padded_steps[:10], start=1):
            out_steps.append(_expand_to_min_len(str(s), minlens["step"], f"步骤{i}", user_question))
        result["steps"] = out_steps
    else:
        padded_steps = _ensure_min_steps(
            [],
            min_count=10,
            user_question=user_question,
            stage_name=stage_name,
        )
        result["steps"] = [
            _expand_to_min_len(str(s), minlens["step"], f"步骤{i}", user_question)
            for i, s in enumerate(padded_steps, start=1)
        ]
    return result


def _norm_cmp_text(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).strip().lower()


def _ensure_unique_outputs(result: Dict[str, object]) -> Dict[str, object]:
    """
    约束关键输出“两两不重复”：
    - 所处逻辑环节（讲解）
    - 正题 / 反题 / 虚假合题 / 真正合题 / 主要矛盾 / 下一环节
    - 启发点 / 通俗化重构参考内容（每条证据）
    """
    used: set[str] = set()

    def _uniquify(text: str, label: str, fallback_seed: str = "") -> str:
        t = str(text or "").strip()
        base_norm = _norm_cmp_text(t)
        if not t:
            t = f"{label}：{fallback_seed or '此处需给出与其他栏目不同的解释与行动含义。'}"
            base_norm = _norm_cmp_text(t)
        if base_norm and base_norm not in used:
            used.add(base_norm)
            return t

        # 若重复，追加“角色差异句”，并按次数递增，确保最终唯一
        i = 2
        while True:
            cand = (
                f"{t}（补充视角{i-1}：这一栏强调的是“{label}”的独立作用，"
                "不与其他栏目重复表达。）"
            )
            n = _norm_cmp_text(cand)
            if n not in used:
                used.add(n)
                return cand
            i += 1

    # 1) 顶层关键栏目
    key_map = [
        ("stage_explanation", "所处逻辑环节"),
        ("thesis", "正题"),
        ("antithesis", "反题"),
        ("false_synthesis", "虚假的合题"),
        ("true_synthesis", "真正的合题"),
        ("contradiction", "主要矛盾"),
        ("next_stage", "下一环节"),
    ]
    for k, label in key_map:
        result[k] = _uniquify(str(result.get(k, "")), label, fallback_seed=str(result.get("stage", "")))

    # 2) 证据区：启发点 / 通俗化重构参考内容
    ev = result.get("inspiring_evidence")
    if isinstance(ev, list):
        out: List[Dict[str, object]] = []
        for idx, item in enumerate(ev, start=1):
            row = dict(item) if isinstance(item, dict) else {"insight": str(item), "quote": ""}
            row["insight"] = _uniquify(
                str(row.get("insight", "")),
                f"启发点{idx}",
                fallback_seed=f"证据{idx}的启发需与其他栏目区分。",
            )
            row["quote"] = _uniquify(
                str(row.get("quote", "")),
                f"通俗化重构参考内容{idx}",
                fallback_seed=f"证据{idx}的重构内容需与其他栏目区分。",
            )
            out.append(row)
        result["inspiring_evidence"] = out
    return result


def analyze_question(
    user_question: str,
    api_key: str = "",
    api_base: str = "",
    model: str = "",
    prefetched_candidates: Optional[List[Dict[str, str]]] = None,
    detail_level: str = "standard",
) -> Dict[str, object]:
    final: Dict[str, object] = {}
    for event in analyze_question_stream(
        user_question,
        api_key=api_key,
        api_base=api_base,
        model=model,
        prefetched_candidates=prefetched_candidates,
        detail_level=detail_level,
    ):
        if event.get("type") == "result":
            payload = event.get("payload")
            if isinstance(payload, dict):
                final = _ensure_unique_outputs(payload)
    return final or {
        "question": user_question,
        "stage": "",
        "stage_explanation": "",
        "thesis": "",
        "antithesis": "",
        "false_synthesis": "",
        "true_synthesis": "",
        "contradiction": "",
        "aufhebung": "",
        "next_stage": "",
        "steps": [],
        "inspiring_evidence": [],
        "analysis_mode": "rule_only",
        "ai_error": "分析流程未返回结果，已回退。",
    }


# 全局缓存，用于存储分析结果
_ANALYSIS_CACHE: Dict[str, Dict[str, object]] = {}


def analyze_question_stream(
    user_question: str,
    api_key: str = "",
    api_base: str = "",
    model: str = "",
    prefetched_candidates: Optional[List[Dict[str, str]]] = None,
    detail_level: str = "standard",
) -> Generator[Dict[str, object], None, None]:
    """分析问题的流式接口，带有缓存优化"""
    _t0 = time.perf_counter()
    metric_inc("analysis_total")
    
    def _record_retrieval_monitor(evidence: object) -> None:
        if not callable(_log_retrieval_quality):
            return
        ev = evidence if isinstance(evidence, list) else []
        citation = 0
        for item in ev:
            if isinstance(item, dict) and (item.get("source_excerpt") or item.get("text")):
                citation += 1
        try:
            _log_retrieval_quality(
                query=user_question,
                hit_count=len(candidate) if isinstance(candidate, list) else 0,
                evidence_count=len(ev),
                citation_count=citation,
            )
        except Exception:
            pass
    
    # 快速检测阶段
    stage = detect_stage(user_question)
    runtime_model = _pick_runtime_model(model, user_question)
    lvl = (detail_level or "standard").lower()
    
    # 设置运行时参数
    if lvl == "concise":
        runtime_max_tokens = min(1200, max(700, LLM_MAX_TOKENS))
        runtime_chunk_chars = max(140, FAST_CHARS_PER_CHUNK)
        runtime_total_chars = max(520, FAST_TOTAL_CHARS)
    elif lvl == "detailed":
        runtime_max_tokens = min(1800, max(1100, LLM_MAX_TOKENS))
        runtime_chunk_chars = max(220, FAST_CHARS_PER_CHUNK)
        runtime_total_chars = max(860, FAST_TOTAL_CHARS)
    else:
        runtime_max_tokens = min(1500, max(900, LLM_MAX_TOKENS))
        runtime_chunk_chars = max(180, FAST_CHARS_PER_CHUNK)
        runtime_total_chars = max(680, FAST_TOTAL_CHARS)
    
    # 使用预取的候选或进行检索
    yield {"type": "status", "message": "正在检索资料（混合检索）..."}
    candidate = prefetched_candidates if isinstance(prefetched_candidates, list) else None
    if candidate is None:
        candidate = search_chunks(user_question, top_k=FAST_SEARCH_TOP_K)
    yield {"type": "status", "message": f"检索完成：命中 {len(candidate)} 条（已 rerank Top3 + small-to-big）。"}
    
    # 生成缓存键
    cache_key = _make_cache_key(user_question, detail_level, runtime_model, candidate)
    
    # 检查内存缓存
    if cache_key in _ANALYSIS_CACHE:
        cached_payload = dict(_ANALYSIS_CACHE[cache_key])
        cached_payload = _enforce_result_minimums(cached_payload, detail_level, user_question)
        cached_payload["cache_hit"] = True
        metric_inc("analysis_cache_hit")
        metric_observe("analysis_total_ms", (time.perf_counter() - _t0) * 1000.0)
        _record_retrieval_monitor(cached_payload.get("inspiring_evidence", []))
        yield {"type": "status", "message": "命中内存缓存，直接返回结果。"}
        yield {"type": "result", "payload": cached_payload}
        return
    
    # 检查磁盘缓存
    cache = _load_analysis_cache()
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        cached_payload = dict(cached)
        cached_payload = _enforce_result_minimums(cached_payload, detail_level, user_question)
        cached_payload["cache_hit"] = True
        # 更新内存缓存
        _ANALYSIS_CACHE[cache_key] = cached_payload
        metric_inc("analysis_cache_hit")
        metric_observe("analysis_total_ms", (time.perf_counter() - _t0) * 1000.0)
        _record_retrieval_monitor(cached_payload.get("inspiring_evidence", []))
        yield {"type": "status", "message": "命中本地缓存，直接返回结果。"}
        yield {"type": "result", "payload": cached_payload}
        return
    result = {
        "question": user_question,
        "stage": stage.name,
        "stage_explanation": _default_stage_explanation(
            user_question=user_question,
            stage_name=stage.name,
            thesis=stage.thesis,
            antithesis=stage.antithesis,
            contradiction=stage.contradiction_hint,
            next_stage=stage.next_stage,
        ),
        "thesis": stage.thesis,
        "antithesis": stage.antithesis,
        "false_synthesis": (
            "（规则模式）虚假合题：把正题与反题生硬折中、表面调和，却未触及核心矛盾，仅得暂时平静。"
        ),
        "true_synthesis": (
            "（规则模式）真正合题：经扬弃进入下一环节「"
            + stage.next_stage
            + "」，把对立提升为可执行的统一，并配合下方步骤落实。"
        ),
        "contradiction": stage.contradiction_hint,
        "aufhebung": stage.aufhebung,
        "next_stage": stage.next_stage,
        "steps": stage.plan_steps,
        "inspiring_evidence": candidate[:EVIDENCE_TARGET_COUNT],
        "analysis_mode": "rule_only",
        "ai_error": "",
    }

    if not api_key or not api_base or not model or not candidate:
        result["inspiring_evidence"] = _ensure_evidence_count(
            result.get("inspiring_evidence", []),  # type: ignore[arg-type]
            candidate,
            user_question=user_question,
            detail_level=detail_level,
            target_count=EVIDENCE_TARGET_COUNT,
        )
        result = _enforce_result_minimums(result, detail_level, user_question)
        result = _ensure_unique_outputs(result)
        metric_inc("analysis_rule_only")
        metric_observe("analysis_total_ms", (time.perf_counter() - _t0) * 1000.0)
        _record_retrieval_monitor(result.get("inspiring_evidence", []))
        yield {"type": "result", "payload": result}
        return

    try:
        attempt_chunks = _truncate_chunks(
            candidate,
            max_chunks=FAST_MAX_CHUNKS,
            max_chars_per_chunk=runtime_chunk_chars,
            max_total_chars=runtime_total_chars,
        )
        prompt = _build_prompt(user_question, attempt_chunks, detail_level=detail_level)
        ai: Optional[Dict[str, object]] = None
        if ENABLE_STREAM_PRIMARY:
            yield {"type": "status", "message": f"正在调用 AI（Streaming）... 当前模型：{runtime_model}"}
            stream = _call_llm_json_stream(
                prompt=prompt,
                api_key=api_key,
                api_base=api_base,
                model=runtime_model,
                timeout_s=LLM_READ_TIMEOUT_S,
                max_tokens=runtime_max_tokens,
            )
            try:
                while True:
                    event = next(stream)
                    if event.get("type") == "delta":
                        yield event
            except StopIteration as done:
                ret = done.value
                ai = ret if isinstance(ret, dict) else None
            except Exception:
                # 常见场景：上游连接中断（如 "Response ended prematurely"）。
                # 兜底改走非流式，尽量避免直接回退规则模式。
                yield {
                    "type": "status",
                    "message": "流式返回中断，正在自动切换为非流式重试...",
                }
                ai = _call_llm_json(
                    prompt=prompt,
                    api_key=api_key,
                    api_base=api_base,
                    model=runtime_model,
                    timeout_s=LLM_READ_TIMEOUT_S,
                    max_retries=LLM_MAX_RETRIES,
                    max_tokens=runtime_max_tokens,
                )
        else:
            # 默认非流式：更稳定，通常总耗时更低，失败率更低。
            yield {"type": "status", "message": f"正在调用 AI（稳定模式）... 当前模型：{runtime_model}"}
            ai = _call_llm_json(
                prompt=prompt,
                api_key=api_key,
                api_base=api_base,
                model=runtime_model,
                timeout_s=LLM_READ_TIMEOUT_S,
                max_retries=LLM_MAX_RETRIES,
                max_tokens=runtime_max_tokens,
            )
        if not ai:
            # 流式拿到的文本无法解析时，再做一次强制非流式补救，避免直接回退。
            yield {"type": "status", "message": "AI 返回格式不稳，正在做非流式补救解析..."}
            ai = _call_llm_json(
                prompt=prompt,
                api_key=api_key,
                api_base=api_base,
                model=runtime_model,
                timeout_s=LLM_READ_TIMEOUT_S,
                max_retries=LLM_MAX_RETRIES,
                max_tokens=runtime_max_tokens,
            )
        if not ai:
            result["ai_error"] = "AI 返回无法解析，已回退规则模式。"
            result = _ensure_unique_outputs(result)
            metric_inc("analysis_fallback_rule")
            metric_inc("analysis_parse_fallback")
            metric_observe("analysis_total_ms", (time.perf_counter() - _t0) * 1000.0)
            _record_retrieval_monitor(result.get("inspiring_evidence", []))
            yield {"type": "result", "payload": result}
            return

        if not isinstance(ai, dict):
            result["ai_error"] = "AI 返回格式异常（非 JSON 对象），已回退规则模式。"
            result = _ensure_unique_outputs(result)
            metric_inc("analysis_fallback_rule")
            metric_inc("analysis_parse_fallback")
            metric_observe("analysis_total_ms", (time.perf_counter() - _t0) * 1000.0)
            _record_retrieval_monitor(result.get("inspiring_evidence", []))
            yield {"type": "result", "payload": result}
            return

        stage_ov = _pick_refine_str(ai, "stage_override", "")
        if stage_ov:
            result["stage"] = stage_ov
        result["stage_explanation"] = _pick_refine_str(
            ai, "stage_explain_refine", str(result.get("stage_explanation", ""))
        )

        result["thesis"] = _pick_refine_str(ai, "thesis_refine", str(result.get("thesis", "")))
        result["antithesis"] = _pick_refine_str(ai, "antithesis_refine", str(result.get("antithesis", "")))
        result["false_synthesis"] = _pick_refine_str(
            ai, "false_synthesis_refine", str(result.get("false_synthesis", ""))
        )
        result["true_synthesis"] = _pick_refine_str(
            ai, "true_synthesis_refine", str(result.get("true_synthesis", ""))
        )
        result["contradiction"] = _pick_refine_str(ai, "contradiction_refine", str(result.get("contradiction", "")))
        result["next_stage"] = _pick_refine_str(ai, "next_stage_refine", str(result.get("next_stage", "")))
        result = _enforce_result_minimums(result, detail_level, user_question)

        steps_refine = ai.get("steps_refine")
        if isinstance(steps_refine, list) and steps_refine:
            result["steps"] = [str(s) for s in steps_refine[:10]]

        ev = ai.get("inspiring_evidence")
        if isinstance(ev, list):
            # IMPORTANT: source excerpt must come from full (non-truncated) candidate chunks.
            result["inspiring_evidence"] = _ensure_evidence_count(
                ev,
                candidate,
                user_question=user_question,
                detail_level=detail_level,
                target_count=EVIDENCE_TARGET_COUNT,
            )
        else:
            result["inspiring_evidence"] = _ensure_evidence_count(
                [],
                candidate,
                user_question=user_question,
                detail_level=detail_level,
                target_count=EVIDENCE_TARGET_COUNT,
            )
        result["analysis_mode"] = "ai_enhanced"
        # 保存缓存：仅缓存成功的 AI 增强结果
        if ANALYSIS_CACHE_LIMIT > 0:
            cache[cache_key] = dict(result)
            if len(cache) > ANALYSIS_CACHE_LIMIT:
                # 简单 FIFO: 删除最早插入的若干条
                overflow = len(cache) - ANALYSIS_CACHE_LIMIT
                for k in list(cache.keys())[:overflow]:
                    cache.pop(k, None)
            _save_analysis_cache(cache)
        
        # 更新内存缓存
        _ANALYSIS_CACHE[cache_key] = dict(result)
        # 限制内存缓存大小
        if len(_ANALYSIS_CACHE) > 100:
            # 简单 FIFO: 删除最早插入的若干条
            overflow = len(_ANALYSIS_CACHE) - 100
            for k in list(_ANALYSIS_CACHE.keys())[:overflow]:
                _ANALYSIS_CACHE.pop(k, None)
        
        result = _ensure_unique_outputs(result)
        metric_inc("analysis_ai_enhanced")
        metric_observe("analysis_total_ms", (time.perf_counter() - _t0) * 1000.0)
        _record_retrieval_monitor(result.get("inspiring_evidence", []))
        yield {"type": "result", "payload": result}
        return
    except Exception as ex:
        msg = str(ex)
        low = msg.lower()
        if "max message tokens" in low or "total tokens" in low:
            result["ai_error"] = (
                "AI 上下文超长（模型 token 限制），已回退规则模式。"
                "建议减少资料片段长度或更换更大上下文窗口的 Endpoint。"
            )
        elif "timeout" in low or "timed out" in low:
            result["ai_error"] = (
                "AI 连接或读取超时，已回退规则模式。"
                "火山方舟等接口在高峰或长输出时可能超过一分钟。"
                "可在启动前设置环境变量 HEGEL_LLM_READ_TIMEOUT=180（秒）后重试，或检查网络。"
                f" 详情：{ex}"
            )
        elif isinstance(ex, KeyError):
            result["ai_error"] = (
                "AI 返回数据结构异常（缺少字段），已回退规则模式。"
                f" 详情：{ex!r}"
            )
        else:
            if "expecting ',' delimiter" in low or "json" in low or "decode" in low:
                result["ai_error"] = (
                    "AI 返回文本格式不稳定（JSON 结构异常），已触发自动修复与非流式补救；"
                    "仍失败后回退规则模式。可稍后重试，或减少单次输出复杂度。"
                    f" 详情：{ex}"
                )
            else:
                result["ai_error"] = f"AI 调用失败，已回退规则模式：{ex}"
        result = _enforce_result_minimums(result, detail_level, user_question)
        result = _ensure_unique_outputs(result)
        metric_inc("analysis_fallback_rule")
        if "timeout" in low or "timed out" in low:
            metric_inc("analysis_timeout")
        metric_observe("analysis_total_ms", (time.perf_counter() - _t0) * 1000.0)
        _record_retrieval_monitor(result.get("inspiring_evidence", []))
        yield {"type": "result", "payload": result}
        return

