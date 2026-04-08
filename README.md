# 黑格尔逻辑学对话机（Hegelian-dialectics）

面向真实问题的辩证分析应用：输入生活/学习/工作困境，输出结构化分析与证据支撑，并提供质量优先的 API 管线（召回、重排、生成、校验、修复）。

---

## 项目定位

本项目不是通用闲聊，而是强调：

- 结构化思考（正题/反题/合题/矛盾/下一环节）
- 可解释证据（本地资料库 RAG）
- 质量稳定（回退机制 + schema 校验 + 质量门禁）
- 工程可运行（Windows 一键启动、CI/CD、可观测）

---

## 核心能力

- **对话分析主链路**
  - 输出固定结构：逻辑环节、正反题、合题、矛盾、执行步骤、证据片段
  - AI 与规则模式双路径，调用失败自动回退
- **资料库管理**
  - 支持 `epub/txt/md/docx`
  - 一键整理资料库：同步、去重、对照、重建索引
- **质量优先 API 管线**
  - `retrieve -> rerank -> generate -> validate -> repair -> score`
  - 可选接入 Qdrant / Cross-Encoder / LiteLLM / Redis
- **质量评估**
  - 离线检索评测：`retrieval_eval.py`
  - 质量门禁评测：`quality_gate.py`

---

## 技术栈

- **应用层**：Python, Streamlit, FastAPI
- **模型与编排**：LiteLLM, LangGraph
- **检索与重排**：Qdrant（可选）, sentence-transformers（Embedding + Cross-Encoder）
- **缓存与基础设施**：Redis（可选）, requests
- **质量与测试**：jsonschema, pytest, GitHub Actions

---

## 架构概览

```text
用户 -> Streamlit UI
        -> hegel_engine.py（主分析链路）
        -> knowledge_base.py / retrieval.py（资料检索）

API 用户 -> FastAPI (/analyze)
          -> quality_pipeline.py
             -> quality_retriever.py (Qdrant/本地回退)
             -> quality_reranker.py (Cross-Encoder/回退)
             -> quality_llm.py (LiteLLM/回退)
             -> quality_schema.py (校验+修复)
             -> quality_metrics.py (质量评分)
             -> quality_cache.py (Redis/内存缓存)
```

---

## 关键文件

- `app_streamlit.py`：前端 UI
- `hegel_engine.py`：核心分析引擎（主链路）
- `knowledge_base.py`：资料接入、分块、索引与检索
- `retrieval.py`：本地检索排序
- `fastapi_app.py`：质量优先 API 入口
- `quality_pipeline.py`：LangGraph 风格质量管线
- `quality_gate.py`：质量门禁脚本
- `retrieval_eval.py`：离线检索评测
- `telemetry.py`：运行指标采集
- `一键启动-黑格尔对话机.bat`：Windows 一键启动全栈

---

## 快速开始

### Windows 一键启动（推荐）

双击运行：`一键启动-黑格尔对话机.bat`

### 命令行启动 UI

```bash
pip install -r requirements.txt
streamlit run app_streamlit.py
```

### 启动质量优先 API

```bash
uvicorn fastapi_app:app --host 0.0.0.0 --port 8000
```

---

## 评测与测试

- 运行单测：

```bash
pytest -q
```

- 离线检索评测：

```bash
python retrieval_eval.py
```

- 质量门禁评测：

```bash
python quality_gate.py
```

---

## 常用环境变量

- `HEGEL_LLM_READ_TIMEOUT`：LLM 读取超时
- `HEGEL_LLM_MAX_RETRIES`：重试次数
- `HEGEL_SEARCH_TOP_K`：检索候选数
- `HEGEL_RETRIEVER_MODE`：`lexical|hybrid|vector`
- `HEGEL_QDRANT_URL` / `HEGEL_QDRANT_COLLECTION`：Qdrant 配置
- `HEGEL_REDIS_URL`：Redis 缓存配置
- `HEGEL_LITELLM_MODEL` / `HEGEL_LITELLM_BASE_URL`：LiteLLM 路由配置

环境模板见：`config/environments/`

---

## 工程保障

- CI：`.github/workflows/ci.yml`
- CD：`.github/workflows/cd.yml`
- 运维文档：`docs/operations/`

---

## 安全提示

- 本地运行数据默认不入库（见 `.gitignore`）
- 请勿提交真实 API Key / 隐私文档
