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

from knowledge_base import search_chunks


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


# 快速分析：压缩输入/输出 token；HTTP 等待时间与模型/线路有关（方舟常需数十秒以上）
FAST_SEARCH_TOP_K = 12
FAST_MAX_CHUNKS = 4
FAST_CHARS_PER_CHUNK = 220
FAST_TOTAL_CHARS = 880
FAST_RETRY_CHUNKS = 2
FAST_RETRY_CHARS = 120
FAST_RETRY_TOTAL = 320
# 可通过环境变量覆盖，例如：set HEGEL_LLM_READ_TIMEOUT=180
LLM_CONNECT_TIMEOUT_S = _env_int("HEGEL_LLM_CONNECT_TIMEOUT", 15, min_v=5, max_v=120)
LLM_READ_TIMEOUT_S = _env_int("HEGEL_LLM_READ_TIMEOUT", 120, min_v=30, max_v=600)
LLM_MAX_RETRIES = _env_int("HEGEL_LLM_MAX_RETRIES", 2, min_v=0, max_v=8)
LLM_MAX_TOKENS = _env_int("HEGEL_LLM_MAX_TOKENS", 1600, min_v=256, max_v=8192)
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
  "thesis_refine": "正题，{lens['thesis']}",
  "antithesis_refine": "反题，{lens['antithesis']}",
  "false_synthesis_refine": "虚假合题，{lens['false_syn']}",
  "true_synthesis_refine": "真正合题，{lens['true_syn']}",
  "contradiction_refine": "核心矛盾，{lens['contradiction']}",
  "next_stage_refine": "下一环节，{lens['next_stage']}",
  "steps_refine": ["可执行一步", "可执行一步", "可执行一步"]
}}

规则：
1) inspiring_evidence 恰好 2 条；quote 须结合用户问题与片段。
2) 每个字段都要有信息量，但尽量短、直接、可解析。
3) steps_refine 至少3步，每步20字以上。
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


def _call_llm_json(
    prompt: str,
    api_key: str,
    api_base: str,
    model: str,
    timeout_s: int = LLM_READ_TIMEOUT_S,
    max_retries: int = LLM_MAX_RETRIES,
    max_tokens: int = LLM_MAX_TOKENS,
) -> Optional[Dict[str, object]]:
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
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as ex:
            last_error = ex
            if attempt >= max_retries:
                raise RuntimeError(f"Request timeout after retries: {ex}") from ex
            time.sleep(2.0 * (attempt + 1))
    else:
        if last_error:
            raise RuntimeError(f"Request failed: {last_error}") from last_error
        raise RuntimeError("Request failed with unknown timeout error.")

    if resp.status_code >= 400:
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
    try:
        parsed = json.loads(content)
        return _repair_ai_payload(parsed) if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(content[start : end + 1])
            return _repair_ai_payload(parsed) if isinstance(parsed, dict) else None
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
        parsed: Optional[Dict[str, object]] = None
        try:
            loaded = json.loads(content)
            if isinstance(loaded, dict):
                parsed = _repair_ai_payload(loaded)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                loaded = json.loads(content[start : end + 1])
                if isinstance(loaded, dict):
                    parsed = _repair_ai_payload(loaded)
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
    continuation = (
        f"围绕“{label}”去理解现实处境时，关键不在于给出一个抽象判断，而在于把{ctx}中的具体冲突串联成可解释的过程："
        "先看它如何在目标、资源与节奏之间形成长期拉扯，再看这种拉扯怎样在情绪和执行层面不断累积，最后看哪些条件一旦被调整就能让局面出现可验证的变化。"
        "当分析从静态结论转向动态过程后，很多看似互斥的选择会被重新组织为可协调的路径，行动也就不再依赖短时冲动，而是能通过小步试错与持续复盘逐步稳定下来。"
        "这种写法的重点是让判断、依据与行动彼此闭环，使文本既能解释为什么会这样，也能回答下一步该如何做。"
    )

    out = (base + " " + continuation).strip() if base else continuation
    if len(out) < min_chars:
        tail = (
            "继续沿着同一逻辑推进时，需要把每一次执行反馈纳入下一轮判断中，逐步筛出真正有效的动作，"
            "并把无效动作及时剔除，这样才能把阶段性的改善转化为可持续的结构性改进。"
        )
        out = (out + " " + tail).strip()

    return out[: max(min_chars + 120, min_chars)].strip()


def _level_minlens(detail_level: str) -> Dict[str, int]:
    lvl = (detail_level or "standard").lower()
    if lvl == "concise":
        return {
            "thesis": 300,
            "antithesis": 300,
            "false": 420,
            "true": 420,
            "contradiction": 420,
            "next": 260,
            "step": 70,
        }
    if lvl == "detailed":
        return {
            "thesis": 760,
            "antithesis": 760,
            "false": 980,
            "true": 980,
            "contradiction": 980,
            "next": 620,
            "step": 140,
        }
    return {
        "thesis": 520,
        "antithesis": 520,
        "false": 700,
        "true": 700,
        "contradiction": 700,
        "next": 420,
        "step": 100,
    }


def _enforce_result_minimums(result: Dict[str, object], detail_level: str, user_question: str) -> Dict[str, object]:
    minlens = _level_minlens(detail_level)
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

    steps = result.get("steps")
    if isinstance(steps, list):
        out_steps: List[str] = []
        for i, s in enumerate(steps[:5], start=1):
            out_steps.append(_expand_to_min_len(str(s), minlens["step"], f"步骤{i}", user_question))
        result["steps"] = out_steps
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
                final = payload
    return final or {
        "question": user_question,
        "stage": "",
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


def analyze_question_stream(
    user_question: str,
    api_key: str = "",
    api_base: str = "",
    model: str = "",
    prefetched_candidates: Optional[List[Dict[str, str]]] = None,
    detail_level: str = "standard",
) -> Generator[Dict[str, object], None, None]:
    stage = detect_stage(user_question)
    runtime_model = _pick_runtime_model(model, user_question)
    lvl = (detail_level or "standard").lower()
    if lvl == "concise":
        runtime_max_tokens = max(1200, LLM_MAX_TOKENS)
        runtime_chunk_chars = max(280, FAST_CHARS_PER_CHUNK)
        runtime_total_chars = max(900, FAST_TOTAL_CHARS)
    elif lvl == "detailed":
        runtime_max_tokens = max(1800, LLM_MAX_TOKENS)
        runtime_chunk_chars = max(420, FAST_CHARS_PER_CHUNK)
        runtime_total_chars = max(1400, FAST_TOTAL_CHARS)
    else:
        runtime_max_tokens = max(1400, LLM_MAX_TOKENS)
        runtime_chunk_chars = max(340, FAST_CHARS_PER_CHUNK)
        runtime_total_chars = max(1100, FAST_TOTAL_CHARS)
    yield {"type": "status", "message": "正在检索资料（混合检索）..."}
    candidate = prefetched_candidates if isinstance(prefetched_candidates, list) else None
    if candidate is None:
        candidate = search_chunks(user_question, top_k=FAST_SEARCH_TOP_K)
    yield {"type": "status", "message": f"检索完成：命中 {len(candidate)} 条（已 rerank Top3 + small-to-big）。"}
    cache_key = _make_cache_key(user_question, detail_level, runtime_model, candidate)
    cache = _load_analysis_cache()
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        cached_payload = dict(cached)
        cached_payload = _enforce_result_minimums(cached_payload, detail_level, user_question)
        cached_payload["cache_hit"] = True
        yield {"type": "status", "message": "命中本地缓存，直接返回结果。"}
        yield {"type": "result", "payload": cached_payload}
        return
    result = {
        "question": user_question,
        "stage": stage.name,
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
        "inspiring_evidence": candidate[:4],
        "analysis_mode": "rule_only",
        "ai_error": "",
    }

    if not api_key or not api_base or not model or not candidate:
        result = _enforce_result_minimums(result, detail_level, user_question)
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
        yield {"type": "status", "message": f"正在调用 AI（Streaming）... 当前模型：{runtime_model}"}
        stream = _call_llm_json_stream(
            prompt=prompt,
            api_key=api_key,
            api_base=api_base,
            model=runtime_model,
            timeout_s=LLM_READ_TIMEOUT_S,
            max_tokens=runtime_max_tokens,
        )
        ai: Optional[Dict[str, object]] = None
        try:
            while True:
                event = next(stream)
                if event.get("type") == "delta":
                    yield event
        except StopIteration as done:
            ret = done.value
            ai = ret if isinstance(ret, dict) else None
        if not ai:
            result["ai_error"] = "AI 返回无法解析，已回退规则模式。"
            yield {"type": "result", "payload": result}
            return

        if not isinstance(ai, dict):
            result["ai_error"] = "AI 返回格式异常（非 JSON 对象），已回退规则模式。"
            yield {"type": "result", "payload": result}
            return

        stage_ov = _pick_refine_str(ai, "stage_override", "")
        if stage_ov:
            result["stage"] = stage_ov

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
            result["steps"] = [str(s) for s in steps_refine[:5]]

        ev = ai.get("inspiring_evidence")
        if isinstance(ev, list) and ev:
            # IMPORTANT: source excerpt must come from full (non-truncated) candidate chunks.
            result["inspiring_evidence"] = _normalize_inspiring_evidence_length(
                ev[:2],
                candidate,
                user_question=user_question,
                detail_level=detail_level,
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
            result["ai_error"] = f"AI 调用失败，已回退规则模式：{ex}"
        result = _enforce_result_minimums(result, detail_level, user_question)
        yield {"type": "result", "payload": result}
        return

