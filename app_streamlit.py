from __future__ import annotations

import json
import inspect
from pathlib import Path

import streamlit as st

import hegel_engine as _hegel_engine
from knowledge_base import (
    add_uploaded_doc,
    build_index,
    deduplicate_manifest_books,
    reconcile_library_with_manifest,
    load_index,
    load_manifest,
    register_default_books,
    remove_doc,
    search_chunks,
    set_doc_enabled,
)

analyze_question_stream = getattr(_hegel_engine, "analyze_question_stream", None)
if analyze_question_stream is None:
    # 兼容旧进程/旧模块：若流式函数不可见，自动回退为非流式调用，避免导入即崩溃。
    def analyze_question_stream(
        user_question: str,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        prefetched_candidates=None,
        detail_level: str = "standard",
    ):
        analyze_question = getattr(_hegel_engine, "analyze_question", None)
        if callable(analyze_question):
            kwargs = {
                "user_question": user_question,
                "api_key": api_key,
                "api_base": api_base,
                "model": model,
            }
            try:
                sig = inspect.signature(analyze_question)
                if "prefetched_candidates" in sig.parameters:
                    kwargs["prefetched_candidates"] = prefetched_candidates
                if "detail_level" in sig.parameters:
                    kwargs["detail_level"] = detail_level
            except Exception:
                # 取签名失败时保持最小参数调用，避免兼容性崩溃。
                pass
            result = analyze_question(**kwargs)
            yield {"type": "result", "payload": result}
            return
        yield {
            "type": "result",
            "payload": {
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
                "ai_error": "hegel_engine 未提供 analyze_question_stream/analyze_question。",
            },
        }

clear_analysis_cache = getattr(_hegel_engine, "clear_analysis_cache", None)


def call_analyze_stream_compat(
    user_question: str,
    api_key: str = "",
    api_base: str = "",
    model: str = "",
    prefetched_candidates=None,
    detail_level: str = "standard",
):
    """兼容新旧 hegel_engine 的 analyze_question_stream 参数差异。"""
    fn = analyze_question_stream
    kwargs = {
        "user_question": user_question,
        "api_key": api_key,
        "api_base": api_base,
        "model": model,
        "prefetched_candidates": prefetched_candidates,
        "detail_level": detail_level,
    }
    try:
        sig = inspect.signature(fn)
        accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
    except Exception:
        accepted = {
            "user_question": user_question,
            "api_key": api_key,
            "api_base": api_base,
            "model": model,
        }
    return fn(**accepted)

UI_STATE_PATH = Path("data/ui_history.json")


def load_ui_state() -> dict:
    if not UI_STATE_PATH.exists():
        return {"api_profiles": [], "question_history": []}
    try:
        return json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"api_profiles": [], "question_history": []}


def save_ui_state(state: dict) -> None:
    UI_STATE_PATH.parent.mkdir(exist_ok=True)
    UI_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def save_api_profile(state: dict, api_base: str, model: str, api_key: str) -> dict:
    profiles = state.get("api_profiles", [])
    profile = {
        "name": "",
        "api_base": api_base.strip(),
        "model": model.strip(),
        "api_key": api_key.strip(),
    }
    profiles = [
        p
        for p in profiles
        if not (
            p.get("api_base") == profile["api_base"]
            and p.get("model") == profile["model"]
            and p.get("api_key") == profile["api_key"]
        )
    ]
    profiles.insert(0, profile)
    state["api_profiles"] = profiles[:20]
    return state


def save_question_history(state: dict, question: str) -> dict:
    q = question.strip()
    if not q:
        return state
    items = state.get("question_history", [])
    items = [x for x in items if x != q]
    items.insert(0, q)
    state["question_history"] = items[:50]
    return state


st.set_page_config(page_title="黑格尔逻辑学对话机", layout="wide")
st.markdown(
    """
<style>
.main h1 { margin-bottom: 0.2rem; }
.main .block-container { padding-top: 1.2rem; }
.hl-card {
    border: 1px solid #2b7fff33;
    background: linear-gradient(135deg, #f7fbff 0%, #eef6ff 100%);
    border-radius: 12px;
    padding: 12px 14px;
    margin: 8px 0 10px 0;
}
.result-card {
    border: 1px solid #ececec;
    border-radius: 10px;
    padding: 10px 12px;
    margin: 6px 0;
    background: #ffffff;
}
.section-title {
    font-weight: 700;
    font-size: 1.05rem;
    margin-top: 0.2rem;
}
.kb-ops {
    border: 1px solid #e8eefb;
    background: #f8fbff;
    border-radius: 12px;
    padding: 10px 12px;
    margin: 8px 0 12px 0;
}
.kb-hint {
    color: #4b5563;
    font-size: 0.92rem;
    margin-top: 4px;
}
div.stButton > button[kind="primary"] {
    background: #0b63f6;
    border-color: #0b63f6;
    color: white;
    font-weight: 700;
}
</style>
""",
    unsafe_allow_html=True,
)
st.title("AI智能黑格尔逻辑学对话机")
st.caption("目标：围绕黑格尔逻辑环节，输出矛盾诊断、扬弃方向、下一环节与执行步骤。")

tab_qa, tab_kb = st.tabs(["对话分析", "资料库管理"])

with tab_qa:
    ui_state = load_ui_state()
    engine_file = str(getattr(_hegel_engine, "__file__", "unknown"))
    engine_build = str(getattr(_hegel_engine, "ENGINE_BUILD", "unknown"))
    cache_schema = str(getattr(_hegel_engine, "CACHE_SCHEMA_VERSION", "unknown"))
    st.markdown(
        """
<div class="hl-card">
  <div class="section-title">核心入口</div>
  先配置 API（可选）→ 输入问题 → 点击 <b>开始辩证拆解</b>。<br/>
  若未配置 API，系统会自动使用规则回退模式。
</div>
""",
        unsafe_allow_html=True,
    )
    st.caption(f"引擎版本：`{engine_build}` | 缓存版本：`{cache_schema}` | 模块：`{engine_file}`")
    c1, c2 = st.columns([1, 3])
    if c1.button("清空分析缓存", use_container_width=True):
        if callable(clear_analysis_cache):
            clear_analysis_cache()
            st.success("已清空分析缓存。")
        else:
            st.warning("当前运行模块不支持清缓存函数，请重启后重试。")

    st.subheader("AI API 配置（可选，但建议填写）")
    profiles = ui_state.get("api_profiles", [])
    for p in profiles:
        if "name" not in p:
            p["name"] = ""
    profile_labels = ["不使用历史配置"] + [
        f"{(p.get('name') or '未命名配置')} | {p.get('model','')} @ {p.get('api_base','')} (key: ...{p.get('api_key','')[-4:] if p.get('api_key') else 'none'})"
        for p in profiles
    ]
    with st.expander("API 历史与管理", expanded=False):
        selected_profile_idx = st.selectbox(
            "历史 API 配置",
            options=list(range(len(profile_labels))),
            format_func=lambda i: profile_labels[i],
        )
        col_h_api1, col_h_api2, col_h_api3 = st.columns(3)
        if col_h_api1.button("应用所选历史配置"):
            if selected_profile_idx > 0:
                chosen = profiles[selected_profile_idx - 1]
                st.session_state["api_base"] = chosen.get("api_base", "")
                st.session_state["model"] = chosen.get("model", "")
                st.session_state["api_key"] = chosen.get("api_key", "")
                st.session_state["api_profile_name"] = chosen.get("name", "")
                st.success("已应用历史 API 配置。")
                st.rerun()
        if col_h_api2.button("删除所选历史配置"):
            if selected_profile_idx > 0:
                del profiles[selected_profile_idx - 1]
                ui_state["api_profiles"] = profiles
                save_ui_state(ui_state)
                st.success("已删除该历史配置。")
                st.rerun()
        if col_h_api3.button("清空全部 API 历史"):
            ui_state["api_profiles"] = []
            save_ui_state(ui_state)
            st.success("已清空全部 API 历史。")
            st.rerun()

    col_api1, col_api2 = st.columns(2)
    profile_name = st.text_input(
        "配置备注名（可选）",
        value=st.session_state.get("api_profile_name", ""),
        help="例如：OpenAI-正式 / DeepSeek-测试",
    )
    api_base = col_api1.text_input(
        "API Base URL",
        value=st.session_state.get("api_base", "https://api.openai.com/v1"),
        help="按 Cherry Studio 方式填写 OpenAI 兼容地址，例如 https://ark.cn-beijing.volces.com/api/v3",
    )
    model = col_api2.text_input(
        "Endpoint ID",
        value=st.session_state.get("model", "gpt-4o-mini"),
        help="填写可调用的 Endpoint ID（不要填模型展示名）。例如控制台 API 示例中的 model 字段。",
    )
    api_key = st.text_input(
        "API Key",
        value=st.session_state.get("api_key", ""),
        type="password",
        help="可保存到本地历史（明文保存在 data/ui_history.json）。",
    )
    st.session_state["api_base"] = api_base
    st.session_state["model"] = model
    st.session_state["api_key"] = api_key
    st.session_state["api_profile_name"] = profile_name
    if st.button("保存当前 API 配置到历史"):
        ui_state = save_api_profile(ui_state, api_base, model, api_key)
        if ui_state.get("api_profiles"):
            ui_state["api_profiles"][0]["name"] = profile_name.strip()
        save_ui_state(ui_state)
        st.success("已保存 API 配置历史。")

    st.subheader("问题输入")
    q_history = ui_state.get("question_history", [])
    q_labels = ["不使用历史问题"] + q_history
    with st.expander("问题历史与管理", expanded=False):
        selected_q_idx = st.selectbox(
            "历史问题输入",
            options=list(range(len(q_labels))),
            format_func=lambda i: (q_labels[i][:80] + "...") if len(q_labels[i]) > 80 else q_labels[i],
        )
        col_h_q1, col_h_q2, col_h_q3 = st.columns(3)
        if col_h_q1.button("应用所选历史问题"):
            if selected_q_idx > 0:
                st.session_state["question_text"] = q_history[selected_q_idx - 1]
                st.success("已填入历史问题。")
                st.rerun()
        if col_h_q2.button("删除所选历史问题"):
            if selected_q_idx > 0:
                del q_history[selected_q_idx - 1]
                ui_state["question_history"] = q_history
                save_ui_state(ui_state)
                st.success("已删除该历史问题。")
                st.rerun()
        if col_h_q3.button("清空全部问题历史"):
            ui_state["question_history"] = []
            save_ui_state(ui_state)
            st.success("已清空全部问题历史。")
            st.rerun()

    question = st.text_area(
        "请输入你的生活问题",
        height=120,
        placeholder="例如：我知道要学习，但总是拖延，越拖越焦虑。",
        key="question_text",
    )
    detail_mode_label = st.radio("输出长度", ["简洁", "标准", "详细"], horizontal=True, index=1)
    detail_mode = {"简洁": "concise", "标准": "standard", "详细": "detailed"}[detail_mode_label]
    # Pre-fetch：在用户输入阶段预取检索结果，减少点击后的首段等待。
    q_now = question.strip()
    q_last = st.session_state.get("_prefetch_question", "")
    # 预取触发门槛：问题过短不预取，减少无效检索开销
    if len(q_now) >= 8 and q_now != q_last:
        try:
            st.session_state["_prefetch_candidates"] = search_chunks(q_now, top_k=4)
            st.session_state["_prefetch_question"] = q_now
        except Exception:
            st.session_state["_prefetch_candidates"] = []
    prefetched = st.session_state.get("_prefetch_candidates", [])
    if q_now and prefetched:
        st.caption(f"已预取检索候选：{len(prefetched)} 条（点击后直接进入流式生成）")
    st.markdown('<div class="section-title">开始分析</div>', unsafe_allow_html=True)
    if st.button("开始辩证拆解", type="primary", use_container_width=True):
        if not question.strip():
            st.warning("请先输入具体问题。")
        else:
            ui_state = save_question_history(ui_state, question.strip())
            save_ui_state(ui_state)
            status_box = st.empty()
            stream_box = st.empty()
            partial = ""
            result = None
            prefetched_for_call = None
            if st.session_state.get("_prefetch_question", "") == question.strip():
                maybe = st.session_state.get("_prefetch_candidates")
                if isinstance(maybe, list):
                    prefetched_for_call = maybe
            for event in call_analyze_stream_compat(
                question.strip(),
                api_key=api_key.strip(),
                api_base=api_base.strip(),
                model=model.strip(),
                prefetched_candidates=prefetched_for_call,
                detail_level=detail_mode,
            ):
                et = event.get("type")
                if et == "status":
                    status_box.info(str(event.get("message", "")))
                elif et == "delta":
                    partial += str(event.get("text", ""))
                    if partial.strip():
                        stream_box.code(partial[-1200:], language="json")
                elif et == "result":
                    payload = event.get("payload")
                    if isinstance(payload, dict):
                        result = payload
            if result is None:
                st.error("流式分析未返回结果，请重试。")
                st.stop()
            status_box.empty()
            stream_box.empty()
            st.subheader("分析结果")
            if result.get("analysis_mode") == "ai_enhanced":
                st.success("当前为：AI 增强分析（已压缩上下文与输出长度；等待时间受接口与网络影响）。")
            else:
                st.info("当前为：规则回退模式（未使用 AI 或 AI 调用失败）。")
            if result.get("cache_hit"):
                st.info("本次结果来自本地缓存（cache hit）。")
            if result.get("ai_error"):
                st.warning(result["ai_error"])

            stage_block = (
                '<div class="result-card"><b>所处逻辑环节</b><br/>'
                + str(result.get("stage", ""))
                + "<br/><br/>"
                + str(result.get("stage_explanation", ""))
                + "</div>"
            )
            st.markdown(stage_block, unsafe_allow_html=True)
            st.markdown('<div class="result-card"><b>正题</b><br/>' + str(result["thesis"]) + "</div>", unsafe_allow_html=True)
            st.markdown('<div class="result-card"><b>反题</b><br/>' + str(result["antithesis"]) + "</div>", unsafe_allow_html=True)
            st.markdown('<div class="result-card"><b>虚假的合题</b><br/>' + str(result.get("false_synthesis", "（待生成）")) + "</div>", unsafe_allow_html=True)
            st.markdown('<div class="result-card"><b>真正的合题</b><br/>' + str(result.get("true_synthesis", "（待生成）")) + "</div>", unsafe_allow_html=True)
            st.markdown('<div class="result-card"><b>主要矛盾</b><br/>' + str(result["contradiction"]) + "</div>", unsafe_allow_html=True)
            st.markdown('<div class="result-card"><b>下一环节</b><br/>' + str(result["next_stage"]) + "</div>", unsafe_allow_html=True)

            st.markdown("**具体扬弃计划（执行版）**")
            for i, step in enumerate(result["steps"], start=1):
                st.markdown(f"{i}. {step}")

            st.markdown("**能给予启发的相关原文证据片段（通俗化重构长参考）**")
            evidence = result.get("inspiring_evidence", [])
            if not evidence:
                st.info("当前没有检索到相关片段。可先去“资料库管理”重建索引。")
            else:
                for item in evidence:
                    doc_path = item.get("doc_path", "未知来源")
                    chunk_id = item.get("chunk_id", "unknown")
                    title = f"{Path(doc_path).name} / {chunk_id}"
                    with st.expander(title):
                        if item.get("insight"):
                            st.markdown(f"**启发点**：{item['insight']}")
                        if item.get("quote"):
                            st.markdown(f"**通俗化重构参考内容**：{item['quote']}")
                        if item.get("source_excerpt"):
                            st.markdown("**参考原文原句片段**：")
                            st.write(item["source_excerpt"])
                        elif item.get("text"):
                            st.markdown("**参考原文原句片段**：")
                            st.write(item["text"])

with tab_kb:
    st.markdown(
        """
<div class="hl-card">
  <div class="section-title">资料库管理</div>
  统一资料目录：<b>library/</b>。点击一次按钮，自动完成同步、去重、对照与重建索引。
</div>
""",
        unsafe_allow_html=True,
    )
    st.subheader("已接入资料")
    st.markdown('<div class="kb-ops">', unsafe_allow_html=True)
    if st.button("一键整理资料库", type="primary", use_container_width=True, key="kb_one_click_cleanup"):
        register_default_books()
        dedup_stats = deduplicate_manifest_books()
        reconcile_stats = reconcile_library_with_manifest()
        payload = build_index()
        st.success(
            "整理完成："
            f"去重移除 {dedup_stats.get('removed', 0)} 条，"
            f"library 删除重复文件 {dedup_stats.get('files_deleted', 0)} 个，"
            f"清单移除失效记录 {reconcile_stats.get('manifest_removed_missing_upload_records', 0)} 条，"
            f"library 删除孤儿文件 {reconcile_stats.get('library_deleted_orphans', 0)} 个；"
            f"索引现为 {payload.get('doc_count', 0)} 个文档 / {payload.get('chunk_count', 0)} 个片段。"
        )
        failed = int(dedup_stats.get("files_delete_failed", 0)) + int(reconcile_stats.get("library_delete_failed", 0))
        if failed > 0:
            st.warning(f"有 {failed} 个文件删除失败（可能被占用或权限不足）。")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    records = load_manifest()
    if not records:
        st.info("暂无资料，请先同步或上传。")
    else:
        for i, r in enumerate(records):
            col1, col2, col3, col4 = st.columns([6, 2, 2, 2])
            col1.write(Path(r.path).name)
            row_key = f"{i}-{r.id}"
            enabled_now = col2.checkbox("启用", value=r.enabled, key=f"enabled-{row_key}")
            if enabled_now != r.enabled:
                set_doc_enabled(r.path, enabled_now)
                st.rerun()
            if col3.button("移除清单", key=f"remove-{row_key}"):
                remove_doc(r.path, delete_file=False)
                st.rerun()
            if col4.button("删除文件", key=f"delete-{row_key}"):
                remove_doc(r.path, delete_file=True)
                st.rerun()

    st.subheader("导入新资料到 library")
    with st.form("kb_upload_form", clear_on_submit=True):
        uploaded = st.file_uploader(
            "支持 .epub / .txt / .md / .docx",
            type=["epub", "txt", "md", "docx"],
            accept_multiple_files=True,
            key="kb_upload_files",
        )
        upload_submit = st.form_submit_button("导入到统一资料目录", use_container_width=True)

    if upload_submit:
        if not uploaded:
            st.toast("请先选择要上传的文件。", icon="⚠️")
            st.warning("请先选择要上传的文件。")
        else:
            ok = 0
            failed = 0
            failed_names = []
            for f in uploaded:
                try:
                    add_uploaded_doc(f.name, f.read())
                    ok += 1
                except Exception:
                    failed += 1
                    failed_names.append(f.name)
            if ok > 0 and failed == 0:
                st.toast(f"上传成功：{ok} 个文件已导入。", icon="✅")
                st.success(f"上传成功：{ok} 个文件已导入到 library 并加入资料清单。")
                st.rerun()
            elif ok > 0 and failed > 0:
                st.toast(f"部分成功：成功 {ok}，失败 {failed}。", icon="⚠️")
                st.warning(f"部分成功：成功 {ok}，失败 {failed}。失败文件：{', '.join(failed_names[:6])}")
                st.rerun()
            else:
                st.toast("上传失败，请重试。", icon="❌")
                st.error("上传失败：未能导入任何文件，请检查文件格式/权限后重试。")

    idx = load_index()
    st.write(f"当前索引：{idx.get('doc_count', 0)} 个文档，{idx.get('chunk_count', 0)} 个片段。")

