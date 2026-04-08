# 黑格尔逻辑学对话机（Hegelian-dialectics）

一个面向真实生活难题的 **辩证分析系统**：
它不是只给“鸡汤建议”，而是把用户问题拆成可执行结构（正题 / 反题 / 矛盾 / 合题 / 下一环节 / 扬弃计划），并结合本地资料库做检索增强，最终输出可落地行动方案。

---

## 这个项目主要解决什么痛点

现实用户的高频难题通常不是“我不知道道理”，而是：

- 知道该做什么，但做不到，反复内耗
- 目标、资源、健康、关系互相拉扯，难以排序
- 输出建议太抽象，无法今天就执行
- AI 回答容易重复、套话、复读用户原句
- 网络波动时 AI 调用不稳定，体验断裂

本项目围绕以上痛点，做了“结构化 + 可执行 + 抗故障”的方案设计。

---

## 核心能力（按用户价值）

### 1) 辩证结构化分析（不是一句话标签）

对每个问题给出完整模块：

- 所处逻辑环节（详细通俗讲解）
- 正题 / 反题
- 虚假的合题 / 真正的合题
- 主要矛盾
- 下一环节
- 具体扬弃计划（执行版，至少 10 条）

### 2) 人性化输出控制

- 文风偏“真人沟通”，避免 AI 自言自语口吻
- 关键栏目禁止原样复述用户原句，尽量转述表达
- 关键输出做去重约束，减少栏目间重复

### 3) 证据增强（RAG）

- 本地资料库检索相关片段
- 输出“启发点 + 通俗化重构参考内容 + 原文片段”
- 证据数量可配置，自动补齐到目标数量（默认 6 条）

### 4) 稳定性与性能优化

- 默认走稳定模式（非流式）降低失败率
- 流式失败自动降级补救
- JSON 解析容错（常见格式错误自动修复）
- 本地缓存命中可直接返回结果

### 5) Windows 一键启动

- 自动识别 Python / Conda / venv
- 依赖检测与安装
- 端口占用检查与旧进程清理
- 项目目录可移动，不依赖固定盘符

---

## 项目架构

```text
用户输入
   ↓
Streamlit 前端（app_streamlit.py）
   ↓
分析引擎（hegel_engine.py）
   ├─ 逻辑环节识别 / 规则兜底
   ├─ Prompt 构建
   ├─ LLM 调用（稳定模式 + 容错 + 重试）
   ├─ 输出后处理（字数下限、去重、去复读）
   └─ 结果缓存
   ↓
知识库（knowledge_base.py）
   ├─ 文档接入（epub/txt/md/docx）
   ├─ 分块与索引
   └─ 检索与候选片段返回
```

---

## 全技术栈（完整）

### 运行与语言

- Python 3.10+
- Streamlit（Web UI）
- requests（OpenAI 兼容 API 调用）

### 核心模块

- `hegel_engine.py`：辩证分析引擎、LLM 调用、输出约束、缓存
- `knowledge_base.py`：资料接入、索引、检索
- `app_streamlit.py`：交互界面与流程编排
- `hegel_dialogue_machine.py`：命令行入口

### 数据与存储

- 本地 JSON（缓存、UI 历史、索引元信息）
- 本地文件系统（`data/`、`uploads/`、`hegel-books/`）

### 调用协议与兼容

- OpenAI-compatible Chat Completions API
- 支持多种第三方网关（如火山方舟等）
- 流式/非流式双模式，默认稳定优先

### 运维与启动（Windows）

- PowerShell：`start-hegel-app.ps1`
- Batch：`一键启动-黑格尔对话机.bat`

---

## 目录结构

```text
.
├─ app_streamlit.py
├─ hegel_engine.py
├─ knowledge_base.py
├─ hegel_dialogue_machine.py
├─ start-hegel-app.ps1
├─ 一键启动-黑格尔对话机.bat
├─ requirements.txt
├─ data/                  # 运行缓存与索引（默认不入库）
├─ uploads/               # 上传资料（默认不入库）
└─ hegel-books/           # 本地书籍资料（默认不入库）
```

---

## 快速开始

### 方式 A：Windows 一键启动（推荐）

双击：

- `一键启动-黑格尔对话机.bat`

脚本会自动：

- 定位 Python 运行时（venv / conda / system python）
- 检查并安装依赖
- 拉起 Streamlit 并打开浏览器

### 方式 B：命令行启动

```bash
pip install -r requirements.txt
streamlit run app_streamlit.py
```

---

## 使用流程（建议）

1. 在“资料库管理”同步 `hegel-books` 或上传文档
2. 点击“重建索引”
3. 在“对话分析”页填写 API 信息（可选保存历史）
4. 输入生活问题并开始分析
5. 根据“具体扬弃计划（执行版）”先执行最小动作，再复盘

---

## 关键可调参数（性能 / 稳定性）

常用环境变量示例（均为可选）：

- `HEGEL_STREAM_PRIMARY`：是否优先流式（默认 0，稳定模式）
- `HEGEL_LLM_MAX_RETRIES`：请求重试次数
- `HEGEL_LLM_READ_TIMEOUT`：读取超时秒数
- `HEGEL_LLM_RETRY_BACKOFF`：重试退避间隔
- `HEGEL_SEARCH_TOP_K`：检索候选数量
- `HEGEL_FAST_MAX_CHUNKS`：送入模型的片段数
- `HEGEL_FAST_TOTAL_CHARS`：模型上下文总字符预算
- `HEGEL_EVIDENCE_COUNT`：证据输出目标条数

说明：项目已做默认优化，不设置也可直接使用。

---

## 隐私与数据安全

- 默认通过 `.gitignore` 排除 `data/`、`uploads/`、`.cursor/`、缓存与本地历史
- API Key 存在本地 `data/ui_history.json`（明文），请自行做好本机安全
- 请勿把私密资料与密钥提交到远程仓库

---

## 典型适用场景

- 学习 / 工作 / 健康节奏冲突
- 自律反复、执行断裂、短期麻痹循环
- 关系与目标冲突导致的长期内耗
- 想要“可执行计划”而不是泛泛建议

---

## 当前状态

项目持续迭代中，重点方向：

- 更稳的 AI 解析与失败补救
- 更快的响应速度与更低回退率
- 更人性化、低复读的输出体验

欢迎基于实际使用反馈继续迭代。
