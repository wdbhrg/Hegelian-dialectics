# AI智能黑格尔逻辑学对话机（知识库可视化版）

这个项目基于你提供的《黑格尔的逻辑学》文本，并可接入 `hegel-books` 目录全部资料，做成了可视化可维护系统：

- 用户输入生活问题
- 系统识别问题所属黑格尔逻辑环节
- 输出正题/反题/矛盾/扬弃/下一环节/执行步骤
- 同时检索资料库原文片段作为依据
- 支持资料上传、启用/禁用、移除、删除、重建索引

## 1. 快速运行

要求：`Python 3.10+`

### 一键启动（推荐）

直接双击项目根目录下：

- `一键启动-黑格尔对话机.bat`

它会自动：

- 检查 Python / pip
- 安装依赖
- 检查 8501 端口
- 启动 Web 界面并打开浏览器

说明：

- `.bat` 只是启动入口，实际逻辑在 `start-hegel-app.ps1`，这样可以显著减少中文乱码问题。
- 启动器已支持 conda：
  - 若当前已激活非 `base` 环境，直接使用当前环境
  - 若当前是 `base` 或未激活环境，优先尝试 `hegel` 环境
  - 可通过环境变量 `HEGEL_CONDA_ENV` 指定环境名

在项目目录执行：

```bash
chcp 65001
pip install -r requirements.txt
streamlit run app_streamlit.py
```

浏览器打开后，你会看到两个页面：

- `对话分析`：输入问题，获得辩证拆解与行动计划
- `资料库管理`：同步 `hegel-books`、上传新资料、增删启用资料、重建索引

## 1.1 AI API 增强（推荐）

在 `对话分析` 页面可填写：

- API Base URL（OpenAI 兼容接口）
- Endpoint ID（模型可调用 ID）
- API Key

填写后，系统会进入“AI 增强分析模式”：

- 先从资料库召回候选片段
- 再由 AI 识别“最能启发当前问题”的证据
- 输出更贴合用户问题的矛盾、扬弃方向与步骤

## 2. 资料接入与动态增删

- 默认会从 `hegel-books` 扫描并接入：`.epub / .txt / .md / .docx`
- 可手动上传新文档进入 `uploads` 并纳入清单
- 每个文档可：
  - 启用（参与问答检索）
  - 移除清单（不删文件）
  - 删除文件（从磁盘删除）
- 每次变更后可一键“重建索引”

## 3. 输出结构（固定）

每次分析固定输出：

每次输出固定包含：

1. 所处逻辑环节
2. 正题
3. 反题
4. 主要矛盾
5. 扬弃方向
6. 下一环节
7. 3步行动计划
8. 能给予启发的相关原文证据片段（可引用或概括转述）

## 4. 项目文件说明

- `app_streamlit.py`：可视化界面
- `knowledge_base.py`：资料清单、文本抽取、分块、索引、检索
- `hegel_engine.py`：黑格尔环节映射与问题分析
## 6. 性能与并行配置（可选）

可通过环境变量调优（Windows PowerShell 示例）：

```powershell
$env:HEGEL_LLM_READ_TIMEOUT="180"
$env:HEGEL_LLM_MAX_RETRIES="2"
$env:HEGEL_LLM_MAX_TOKENS="1600"
```

轻量模型路由（用于“总结/摘要/归纳”类任务）：

```powershell
$env:HEGEL_ENABLE_LIGHT_ROUTER="1"
$env:HEGEL_LIGHT_MODEL="gemma-3-4b-it"
```

KV Cache 提示（仅当你的网关/模型兼容该参数时生效）：

```powershell
$env:HEGEL_KV_CACHE_ENABLED="1"
```

说明：
- 项目已实现混合检索（关键词预筛 + 语义近似）、Rerank Top3、Small-to-Big 上下文扩展。
- 已支持 Streaming 流式输出与输入阶段预取检索（Pre-fetch）。
- `hegel_engine.py` 提供 `summarize_documents_parallel()`，可并行总结多文档再汇总。
- `hegel_dialogue_machine.py`：命令行版本（可保留备用）

## 5. 落地使用建议

给普通用户时，建议按 7 天循环：

- 第 1 天：输入问题，得到矛盾与计划
- 第 2-6 天：执行计划并记录反馈
- 第 7 天：把执行结果再次输入系统，生成下一轮扬弃

这样就把黑格尔逻辑从“哲学阅读”变成“可迭代的问题解决系统”。
