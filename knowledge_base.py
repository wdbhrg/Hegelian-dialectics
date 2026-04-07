from __future__ import annotations

import html
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple


DATA_DIR = Path("data")
UPLOAD_DIR = Path("uploads")
DEFAULT_BOOK_DIR = Path("hegel-books")
MANIFEST_PATH = DATA_DIR / "manifest.json"
INDEX_PATH = DATA_DIR / "index.json"
_INDEX_CACHE: Dict[str, object] | None = None
_INDEX_MTIME_NS: int = -1


@dataclass
class DocRecord:
    id: str
    path: str
    enabled: bool = True


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    DEFAULT_BOOK_DIR.mkdir(exist_ok=True)


def _safe_doc_id(path: Path) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-\.]", "_", str(path).lower())


def load_manifest() -> List[DocRecord]:
    ensure_dirs()
    if not MANIFEST_PATH.exists():
        return []
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return [DocRecord(**item) for item in data]


def save_manifest(records: List[DocRecord]) -> None:
    ensure_dirs()
    MANIFEST_PATH.write_text(
        json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_default_books() -> List[DocRecord]:
    ensure_dirs()
    existing = {r.path: r for r in load_manifest()}
    for p in DEFAULT_BOOK_DIR.glob("*"):
        if p.is_file() and p.suffix.lower() in {".epub", ".txt", ".md", ".docx"}:
            key = str(p.resolve())
            if key not in existing:
                existing[key] = DocRecord(id=_safe_doc_id(p), path=key, enabled=True)
    records = list(existing.values())
    save_manifest(records)
    return records


def set_doc_enabled(doc_path: str, enabled: bool) -> None:
    records = load_manifest()
    for r in records:
        if r.path == doc_path:
            r.enabled = enabled
    save_manifest(records)


def remove_doc(doc_path: str, delete_file: bool = False) -> None:
    records = [r for r in load_manifest() if r.path != doc_path]
    save_manifest(records)
    if delete_file:
        p = Path(doc_path)
        if p.exists() and p.is_file():
            p.unlink()


def add_uploaded_doc(filename: str, content: bytes) -> str:
    ensure_dirs()
    target = UPLOAD_DIR / filename
    stem, suffix = target.stem, target.suffix
    counter = 1
    while target.exists():
        target = UPLOAD_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    target.write_bytes(content)

    records = load_manifest()
    records.append(DocRecord(id=_safe_doc_id(target), path=str(target.resolve()), enabled=True))
    save_manifest(records)
    return str(target.resolve())


def _strip_html(raw: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _decode_text_bytes(data: bytes) -> str:
    # 常见中文电子书/文本编码兜底顺序
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk", "big5"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _repair_mojibake(text: str) -> str:
    # 典型 UTF-8 被按 latin1 误解后的乱码特征（如“æ³•å…”）
    suspicious = "ÃÂÆÐÑØÙàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ"
    score = sum(1 for ch in text if ch in suspicious)
    if score < max(8, len(text) // 120):
        return text
    try:
        fixed = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        return text
    # 只有在中文字符数量明显提升时才采用修复结果
    cjk_old = len(re.findall(r"[\u4e00-\u9fff]", text))
    cjk_new = len(re.findall(r"[\u4e00-\u9fff]", fixed))
    return fixed if cjk_new > cjk_old else text


def _extract_from_docx(path: Path) -> str:
    with zipfile.ZipFile(path, "r") as zf:
        data = _decode_text_bytes(zf.read("word/document.xml"))
    text = re.sub(r"</w:p>", "\n", data)
    text = re.sub(r"<[^>]+>", "", text)
    return _repair_mojibake(html.unescape(text))


def _extract_from_epub(path: Path) -> str:
    paragraphs: List[str] = []
    with zipfile.ZipFile(path, "r") as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
        for name in names:
            raw = _decode_text_bytes(zf.read(name))
            cleaned = _strip_html(raw)
            if cleaned:
                paragraphs.append(cleaned)
    return _repair_mojibake("\n".join(paragraphs))


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return _repair_mojibake(_decode_text_bytes(path.read_bytes()))
    if suffix == ".docx":
        return _extract_from_docx(path)
    if suffix == ".epub":
        return _extract_from_epub(path)
    return ""


def _chunk_text(text: str, chunk_size: int = 800) -> List[str]:
    parts = [p.strip() for p in re.split(r"[\n\r]+", text) if p.strip()]
    chunks: List[str] = []
    current = ""
    for p in parts:
        if len(current) + len(p) + 1 <= chunk_size:
            current = f"{current}\n{p}" if current else p
        else:
            if current:
                chunks.append(current)
            current = p
    if current:
        chunks.append(current)
    return chunks


def build_index() -> Dict[str, object]:
    global _INDEX_CACHE, _INDEX_MTIME_NS
    records = register_default_books()
    chunks: List[Dict[str, str]] = []
    doc_count = 0
    for r in records:
        if not r.enabled:
            continue
        p = Path(r.path)
        if not p.exists() or not p.is_file():
            continue
        text = _extract_text(p)
        if not text.strip():
            continue
        doc_count += 1
        for idx, chunk in enumerate(_chunk_text(text)):
            chunks.append(
                {
                    "doc_path": r.path,
                    "chunk_id": f"{r.id}-{idx}",
                    "text": chunk,
                }
            )
    payload = {"doc_count": doc_count, "chunk_count": len(chunks), "chunks": chunks}
    ensure_dirs()
    INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _INDEX_CACHE = payload
    try:
        _INDEX_MTIME_NS = INDEX_PATH.stat().st_mtime_ns
    except Exception:
        _INDEX_MTIME_NS = -1
    return payload


def load_index() -> Dict[str, object]:
    global _INDEX_CACHE, _INDEX_MTIME_NS
    ensure_dirs()
    if not INDEX_PATH.exists():
        return build_index()
    try:
        mtime_ns = INDEX_PATH.stat().st_mtime_ns
    except Exception:
        mtime_ns = -1
    if _INDEX_CACHE is not None and _INDEX_MTIME_NS == mtime_ns:
        return _INDEX_CACHE
    payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    _INDEX_CACHE = payload if isinstance(payload, dict) else {}
    _INDEX_MTIME_NS = mtime_ns
    return _INDEX_CACHE


def _tokenize_query(query: str) -> List[str]:
    q = query.strip().lower()
    if not q:
        return []
    latin_tokens = re.findall(r"[a-z0-9_]+", q)
    han = re.sub(r"[^\u4e00-\u9fff]", "", q)
    han_bigrams = [han[i : i + 2] for i in range(max(len(han) - 1, 0))]
    han_unigrams = list(han) if len(han) <= 2 else []
    tokens = latin_tokens + han_bigrams + han_unigrams
    if not tokens:
        tokens = [q]
    # remove very short duplicate noise
    dedup: List[str] = []
    seen = set()
    for t in tokens:
        if t and t not in seen:
            seen.add(t)
            dedup.append(t)
    return dedup


def _char_bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _semantic_proxy_score(query: str, text: str) -> float:
    # 轻量“语义近似”：基于中文双字切片/Jaccard，避免额外模型依赖。
    q_han = re.sub(r"[^\u4e00-\u9fff]", "", query.lower())
    t_han = re.sub(r"[^\u4e00-\u9fff]", "", text.lower())
    if not q_han or not t_han:
        return 0.0
    q_set = _char_bigrams(q_han)
    t_set = _char_bigrams(t_han)
    if not q_set or not t_set:
        return 0.0
    inter = len(q_set & t_set)
    union = len(q_set | t_set)
    return inter / union if union else 0.0


def _parse_chunk_order(chunk_id: str) -> Tuple[str, int]:
    if "-" not in chunk_id:
        return chunk_id, 0
    prefix, tail = chunk_id.rsplit("-", 1)
    try:
        return prefix, int(tail)
    except ValueError:
        return prefix, 0


def _expand_chunk_context(anchor: Dict[str, str], by_doc: Dict[str, Dict[int, Dict[str, str]]]) -> Dict[str, str]:
    # small-to-big: 检索命中小块，但返回上下文（前后各1块）给 LLM。
    doc_path = str(anchor.get("doc_path", ""))
    chunk_id = str(anchor.get("chunk_id", ""))
    _, idx = _parse_chunk_order(chunk_id)
    doc_map = by_doc.get(doc_path, {})
    parts: List[str] = []
    for i in (idx - 1, idx, idx + 1):
        c = doc_map.get(i)
        if c:
            txt = str(c.get("text", "")).strip()
            if txt:
                parts.append(txt)
    merged = "\n\n".join(parts).strip() or str(anchor.get("text", ""))
    item = dict(anchor)
    item["text"] = merged
    return item


def search_chunks(query: str, top_k: int = 5) -> List[Dict[str, str]]:
    index = load_index()
    chunks = index.get("chunks", [])
    q_terms = _tokenize_query(query)
    if not q_terms:
        return []

    # 1) 关键词预筛：先过滤掉大部分无关片段（大海捞针 -> 精准打击）
    prefiltered: List[Tuple[int, Dict[str, str]]] = []
    for ch in chunks:
        text = ch["text"].lower()
        lexical_score = 0
        for t in q_terms:
            if t in text:
                weight = 2 if len(t) == 2 else 1
                lexical_score += text.count(t) * weight
        if lexical_score > 0:
            prefiltered.append((lexical_score, ch))
    if not prefiltered:
        return []

    prefiltered.sort(key=lambda x: x[0], reverse=True)
    # 仅保留前 20%（至少 12 条）进入语义近似匹配
    keep_n = max(12, int(len(prefiltered) * 0.2))
    pool = prefiltered[:keep_n]

    # 2) 混合打分：关键词 + 语义近似（轻量，无额外依赖）
    def _score_one(item: Tuple[int, Dict[str, str]]) -> Tuple[float, Dict[str, str]]:
        lexical_score, ch = item
        sem = _semantic_proxy_score(query, str(ch.get("text", "")))
        score = float(lexical_score) * 0.75 + sem * 0.25 * 100
        return score, ch

    # 并行打分：对候选池并发计算语义近似分，降低重排阶段耗时。
    workers = min(8, max(2, len(pool)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        hybrid_scored = list(ex.map(_score_one, pool))
    hybrid_scored.sort(key=lambda x: x[0], reverse=True)

    # 3) Rerank：只取 Top3（若 top_k 更小则按 top_k）
    rerank_k = min(3, max(1, top_k))
    anchors = [ch for _, ch in hybrid_scored[:rerank_k]]

    # 4) small-to-big：返回命中块周边上下文
    by_doc: Dict[str, Dict[int, Dict[str, str]]] = {}
    for ch in chunks:
        doc_path = str(ch.get("doc_path", ""))
        chunk_id = str(ch.get("chunk_id", ""))
        _, idx = _parse_chunk_order(chunk_id)
        by_doc.setdefault(doc_path, {})[idx] = ch

    expanded = [_expand_chunk_context(a, by_doc) for a in anchors]
    return expanded
