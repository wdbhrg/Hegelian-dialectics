from __future__ import annotations

import html
import json
import hashlib
import re
import shutil
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

from retrieval import retrieve_ranked_chunks

DATA_DIR = Path("data")
LIBRARY_DIR = Path("library")
# backward-compat aliases (kept for existing call sites/env expectations)
UPLOAD_DIR = LIBRARY_DIR
DEFAULT_BOOK_DIR = LIBRARY_DIR
LEGACY_UPLOAD_DIR = Path("uploads")
LEGACY_BOOK_DIR = Path("hegel-books")
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
    LIBRARY_DIR.mkdir(exist_ok=True)
    _migrate_legacy_dirs_into_library()


def _unique_library_target(name: str) -> Path:
    target = LIBRARY_DIR / name
    stem, suffix = target.stem, target.suffix
    counter = 1
    while target.exists():
        target = LIBRARY_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    return target


def _migrate_legacy_dirs_into_library() -> None:
    """
    将旧目录 uploads/ 与 hegel-books/ 中的资料自动并入 library/。
    保留文件内容，遇到同名则自动改名，避免覆盖。
    """
    for old_dir in (LEGACY_UPLOAD_DIR, LEGACY_BOOK_DIR):
        if old_dir.resolve() == LIBRARY_DIR.resolve():
            continue
        if not old_dir.exists() or not old_dir.is_dir():
            continue
        for p in old_dir.glob("*"):
            if not p.is_file() or p.suffix.lower() not in {".epub", ".txt", ".md", ".docx"}:
                continue
            target = _unique_library_target(p.name)
            try:
                shutil.move(str(p), str(target))
            except Exception:
                # 迁移失败不阻断主流程，后续仍可由用户手动处理。
                pass


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
    for p in LIBRARY_DIR.glob("*"):
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
    target = LIBRARY_DIR / filename
    stem, suffix = target.stem, target.suffix
    counter = 1
    while target.exists():
        target = LIBRARY_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    target.write_bytes(content)

    records = load_manifest()
    records.append(DocRecord(id=_safe_doc_id(target), path=str(target.resolve()), enabled=True))
    save_manifest(records)
    return str(target.resolve())


def _normalized_path_key(path_str: str) -> str:
    p = Path(path_str)
    try:
        return str(p.resolve()).lower()
    except Exception:
        return str(p).strip().lower()


def _file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _record_priority(rec: DocRecord) -> Tuple[int, int, int]:
    """
    选择保留记录时的优先级：
    1) enabled=True 优先
    2) 文件存在优先
    3) 默认书库目录优先
    """
    p = Path(rec.path)
    exists = int(p.exists() and p.is_file())
    try:
        in_default = int(LIBRARY_DIR.resolve().as_posix().lower() in p.resolve().as_posix().lower())
    except Exception:
        in_default = 0
    return (int(rec.enabled), exists, in_default)


def deduplicate_manifest_books() -> Dict[str, int]:
    """
    清理 manifest 中重复书籍，仅保留一份。
    判重规则（严格）：
    - 文件存在时：按文件内容 SHA1 判重（内容一致即重复）
    - 文件不存在时：按规范化路径判重（兜底）
    """
    records = load_manifest()
    if not records:
        return {"before": 0, "after": 0, "removed": 0, "files_deleted": 0, "files_delete_failed": 0}

    chosen: Dict[Tuple[str, str], DocRecord] = {}
    order: List[Tuple[str, str]] = []
    hash_cache: Dict[str, str] = {}

    for rec in records:
        norm_path = _normalized_path_key(rec.path)
        path_group = ("path", norm_path)

        p = Path(rec.path)
        content_group: Tuple[str, str] | None = None
        try:
            if p.exists() and p.is_file():
                if norm_path in hash_cache:
                    sha1 = hash_cache[norm_path]
                else:
                    sha1 = _file_sha1(p)
                    hash_cache[norm_path] = sha1
                content_group = ("sha1", sha1)
        except Exception:
            content_group = None

        group_key = content_group or path_group

        if group_key not in chosen:
            chosen[group_key] = rec
            order.append(group_key)
            continue

        old = chosen[group_key]
        if _record_priority(rec) > _record_priority(old):
            chosen[group_key] = rec

    deduped = [chosen[k] for k in order]
    before = len(records)
    after = len(deduped)
    removed = max(0, before - after)
    files_deleted = 0
    files_delete_failed = 0

    if removed > 0:
        # 只删除“被去重淘汰”且位于统一资料目录 library/ 的文件，避免误删外部文件。
        kept_norm_paths = {_normalized_path_key(r.path) for r in deduped}
        try:
            library_root = str(LIBRARY_DIR.resolve()).lower()
        except Exception:
            library_root = str(LIBRARY_DIR).lower()

        # 计算被淘汰记录（多次重复记录可能指向同一路径，去重后再删）
        dropped_norm_paths: set[str] = set()
        for r in records:
            norm = _normalized_path_key(r.path)
            if norm not in kept_norm_paths:
                dropped_norm_paths.add(norm)

        for norm in dropped_norm_paths:
            try:
                p = Path(norm)
                # 仅清理 library 目录下的真实文件
                in_library = str(p.resolve()).lower().startswith(library_root)
                if in_library and p.exists() and p.is_file():
                    p.unlink()
                    files_deleted += 1
            except Exception:
                files_delete_failed += 1

        save_manifest(deduped)

    return {
        "before": before,
        "after": after,
        "removed": removed,
        "files_deleted": files_deleted,
        "files_delete_failed": files_delete_failed,
    }


def reconcile_library_with_manifest() -> Dict[str, int]:
    """
    将 library/ 与 manifest 中资料记录一一对照并同步：
    - 删除 library 中未被 manifest 引用的孤儿文件
    - 删除 manifest 中指向 library 但文件已不存在的记录
    """
    records = load_manifest()
    try:
        library_root = str(LIBRARY_DIR.resolve()).lower()
    except Exception:
        library_root = str(LIBRARY_DIR).lower()

    def _is_upload_path(path_str: str) -> bool:
        try:
            return str(Path(path_str).resolve()).lower().startswith(library_root)
        except Exception:
            return str(path_str).lower().startswith(library_root)

    # 1) 清理 manifest 中失效的 library 记录（文件不存在）
    missing_upload_records = 0
    kept_records: List[DocRecord] = []
    for r in records:
        if _is_upload_path(r.path):
            p = Path(r.path)
            if not (p.exists() and p.is_file()):
                missing_upload_records += 1
                continue
        kept_records.append(r)

    # 2) 删除 library 中未被清单引用的孤儿文件
    referenced_uploads = {_normalized_path_key(r.path) for r in kept_records if _is_upload_path(r.path)}
    orphan_files_deleted = 0
    orphan_files_delete_failed = 0

    ensure_dirs()
    for f in LIBRARY_DIR.glob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in {".epub", ".txt", ".md", ".docx"}:
            continue
        norm = _normalized_path_key(str(f))
        if norm in referenced_uploads:
            continue
        try:
            f.unlink()
            orphan_files_deleted += 1
        except Exception:
            orphan_files_delete_failed += 1

    # 3) 写回 manifest（仅当发生变化）
    if missing_upload_records > 0 or len(kept_records) != len(records):
        save_manifest(kept_records)

    return {
        "manifest_before": len(records),
        "manifest_after": len(kept_records),
        "manifest_removed_missing_upload_records": missing_upload_records,
        "library_deleted_orphans": orphan_files_deleted,
        "library_delete_failed": orphan_files_delete_failed,
        # backward-compat keys
        "uploads_deleted_orphans": orphan_files_deleted,
        "uploads_delete_failed": orphan_files_delete_failed,
    }


def reconcile_uploads_with_manifest() -> Dict[str, int]:
    # backward-compat alias
    return reconcile_library_with_manifest()


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


# 全局缓存，用于存储by_doc字典
_BY_DOC_CACHE: Dict[str, Dict[str, Dict[int, Dict[str, str]]]] = {}


def search_chunks(query: str, top_k: int = 5) -> List[Dict[str, str]]:
    """搜索 chunks，带有缓存机制"""
    global _BY_DOC_CACHE
    
    index = load_index()
    chunks = index.get("chunks", [])
    if not query.strip():
        return []
    
    # 生成缓存键
    cache_key = str(len(chunks))
    
    # 检查缓存
    if cache_key not in _BY_DOC_CACHE:
        # 构建by_doc字典
        by_doc: Dict[str, Dict[int, Dict[str, str]]] = {}
        for ch in chunks:
            doc_path = str(ch.get("doc_path", ""))
            chunk_id = str(ch.get("chunk_id", ""))
            _, idx = _parse_chunk_order(chunk_id)
            by_doc.setdefault(doc_path, {})[idx] = ch
        # 更新缓存
        _BY_DOC_CACHE = {cache_key: by_doc}
    
    # 使用缓存的by_doc字典
    by_doc = _BY_DOC_CACHE[cache_key]
    
    # 检索排名靠前的chunks
    anchors = retrieve_ranked_chunks(query, chunks, top_k=top_k)
    if not anchors:
        return []

    # small-to-big：返回命中块周边上下文
    expanded = [_expand_chunk_context(a, by_doc) for a in anchors]
    return expanded
