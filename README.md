# Hegelian-dialectics

一个基于黑格尔辩证法（结合齐泽克式问题拆解方向）的 AI 对话系统。  
项目聚焦三件事：**提问分析、知识库检索、可执行行动计划**。

---

## 1. 项目结构

```text
E:\hegel-logic
├─ app_streamlit.py                 # Web UI（对话分析 + 资料库管理）
├─ hegel_engine.py                  # 辩证分析引擎（流式调用、长度控制、缓存）
├─ knowledge_base.py                # 资料库索引与检索（抽取、分块、混合检索）
├─ hegel_dialogue_machine.py        # 命令行版（备用）
├─ start-hegel-app.ps1              # PowerShell 一键启动主逻辑
├─ 一键启动-黑格尔对话机.bat         # Windows 启动入口
├─ requirements.txt                 # 运行依赖
├─ data/                            # 本地运行数据（索引、缓存、UI 历史）
├─ uploads/                         # 用户上传资料
└─ hegel-books/                     # 本地原始资料库（已被 gitignore 排除）
```

---

## 2. 全部技术栈（按层说明）

### 2.1 运行与语言
- **Python 3.10+**：核心语言
- **PowerShell + Batch**：Windows 一键启动与环境探测

### 2.2 前端交互层
- **Streamlit**
  - 表单输入（问题、API 配置）
  - 结果卡片展示
  - 资料库管理（同步、上传、启用/删除、重建索引）
  - 流式输出增量显示

### 2.3 核心引擎层（`hegel_engine.py`）
- **辩证分析框架**：阶段检测、提示词构建、结果结构化
- **OpenAI 兼容 API 调用**
  - 非流式 JSON 调用
  - SSE 流式调用（Streaming）
  - 超时/重试/错误回退
- **输出后处理**
  - 乱码修复（mojibake repair）
  - 字数与结构控制
  - 证据字段标准化
- **本地结果缓存**
  - 分析结果缓存键（问题 + 模式 + 模型 + 片段）
  - 缓存清理入口

### 2.4 知识库与检索层（`knowledge_base.py`）
- **多格式文本抽取**：`.epub / .docx / .txt / .md`
- **编码鲁棒性**
  - UTF-8/GBK/GB18030/BIG5 自动解码兜底
  - 乱码修复
- **索引构建**
  - 文本分块（chunk）
  - 索引存储到 `data/index.json`
  - 内存索引缓存（按 mtime 自动失效）
- **检索策略**
  - 关键词预筛
  - 轻量语义近似打分（bigrams + Jaccard）
  - Rerank TopK
  - Small-to-Big 上下文扩展

### 2.5 数据与状态层
- **JSON 本地存储**
  - `data/index.json`（检索索引）
  - `data/analysis_cache.json`（分析缓存）
  - `data/ui_history.json`（API 历史与提问历史）
- **Git 忽略策略**
  - `data/`、`uploads/`、`hegel-books/` 不进仓库

### 2.6 网络与依赖
- **requests**：HTTP 调用模型接口
- **streamlit**：Web UI

---

## 3. 核心能力

1. 用户输入生活问题，系统进行辩证拆解。  
2. 从本地资料库检索最相关片段并生成启发证据。  
3. 输出结构化结果（正题、反题、矛盾、合题、下一环节、执行计划）。  
4. 支持流式展示与规则回退，保证可用性。  
5. 支持资料库维护与索引重建。

---

## 4. 快速运行

### 方式 A：一键启动（推荐，Windows）
双击：

- `一键启动-黑格尔对话机.bat`

启动器会自动检查：
- Python / pip
- 依赖
- 8501 端口
- Streamlit 启动

### 方式 B：命令行启动

```bash
pip install -r requirements.txt
streamlit run app_streamlit.py
```

---

## 5. 可调环境变量（性能/稳定性）

```powershell
$env:HEGEL_LLM_READ_TIMEOUT="180"
$env:HEGEL_LLM_MAX_RETRIES="2"
$env:HEGEL_LLM_MAX_TOKENS="1600"
$env:HEGEL_ENABLE_LIGHT_ROUTER="1"
$env:HEGEL_LIGHT_MODEL="gemma-3-4b-it"
$env:HEGEL_KV_CACHE_ENABLED="1"
$env:HEGEL_ANALYSIS_CACHE_LIMIT="80"
```

---

## 6. 安全与仓库策略

- 仓库只包含代码，不包含资料库原文与本地历史数据。  
- 已通过 `.gitignore` 排除：
  - `hegel-books/`
  - `data/`
  - `uploads/`
  - `doc_extracted.txt`
  - `__pycache__/`

---

## 7. 许可证

当前仓库未附带 license；如需开源发布，建议补充 MIT / Apache-2.0。
