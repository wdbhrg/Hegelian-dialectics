# 黑格尔逻辑学对话机（Hegelian-dialectics）

一个面向真实生活难题的辩证分析工具：把“说不清、做不到、反复内耗”的问题，拆成可执行结构，并结合本地资料做证据增强输出。

---

## 项目定位

这个项目不是“泛泛聊天”，而是解决以下实际痛点：

- 知道道理但无法执行，长期拖延与反复
- 学习 / 工作 / 健康 / 关系目标相互冲突，难以排序
- AI 建议过于抽象，缺少当天可落地动作
- 网络抖动导致调用失败、结构异常、体验断裂

项目目标：在保证结构完整的前提下，输出更快、更稳、更可执行。

---

## 核心功能

### 1) 辩证结构化输出（完整模块）

每次分析输出包含：

- 所处逻辑环节（详细通俗讲解）
- 正题 / 反题
- 虚假的合题 / 真正的合题
- 主要矛盾
- 下一环节
- 具体扬弃计划（执行版，至少 10 条）
- 证据区（启发点 + 通俗化重构参考内容 + 原文片段）

### 2) 输出质量控制

- 关键字段避免原样复读用户原句
- 多栏目输出做去重约束，降低“同句复用”
- 字段有最低字数约束，保证信息密度
- 失败时规则模式兜底，确保始终有结果

### 3) 资料库（RAG）

- 支持 `epub/txt/md/docx` 导入
- 统一资料目录：`library/`
- 一键整理资料库：同步目录 → 严格去重（内容哈希）→ 清单对照 → 重建索引
- 证据数量可配置并自动补齐（默认 6 条）

### 4) 稳定性与性能优化

- 默认稳定模式（非流式主链路）
- 流式失败自动降级重试
- JSON 容错解析（缺逗号/尾逗号等常见异常）
- SSL/连接中断重试与退避
- 本地缓存命中快速返回

### 5) Windows 一键启动

- 自动解析 Python/Conda/venv
- 自动检查依赖
- 端口冲突自动处理（含 fallback 端口）
- 项目目录可移动，不依赖固定盘符

---

## 技术栈（完整）

### 运行层

- Python 3.10+
- Streamlit
- requests

### 核心模块

- `app_streamlit.py`：Web UI 与交互流程
- `hegel_engine.py`：辩证分析引擎、LLM 调用、输出后处理、缓存
- `knowledge_base.py`：文档接入、分块、检索、资料库整理
- `hegel_dialogue_machine.py`：CLI 入口
- `start-hegel-app.ps1` / `一键启动-黑格尔对话机.bat`：Windows 启动链路

### 存储与目录

- `data/`：运行缓存、索引、UI 历史
- `library/`：统一资料目录（上传与本地资料合并）

---

## 架构流程

```text
用户输入
  ↓
Streamlit UI（app_streamlit.py）
  ↓
分析引擎（hegel_engine.py）
  ├─ 环节识别与规则兜底
  ├─ 检索候选融合（来自 knowledge_base）
  ├─ LLM 调用（稳定模式优先 + 容错重试）
  ├─ 输出规范化（字数、去重、去复读）
  └─ 本地缓存
  ↓
结果展示（结构化模块 + 证据区）
```

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
├─ data/       # 运行缓存与索引
└─ library/    # 统一资料目录
```

---

## 快速开始

### 方式 A（推荐，Windows）

双击：`一键启动-黑格尔对话机.bat`

### 方式 B（命令行）

```bash
pip install -r requirements.txt
streamlit run app_streamlit.py
```

---

## 使用建议

1. 打开“资料库管理”
2. 点击“一键整理资料库”
3. 返回“对话分析”输入问题
4. 优先执行计划中的最小动作，再复盘

---

## 关键环境变量（可选）

- `HEGEL_STREAM_PRIMARY`：是否优先流式（默认 0）
- `HEGEL_LLM_MAX_RETRIES`：LLM 重试次数
- `HEGEL_LLM_READ_TIMEOUT`：读取超时秒数
- `HEGEL_LLM_RETRY_BACKOFF`：重试退避秒数
- `HEGEL_SEARCH_TOP_K`：检索候选数量
- `HEGEL_FAST_MAX_CHUNKS`：送模片段数
- `HEGEL_FAST_TOTAL_CHARS`：送模总字符预算
- `HEGEL_EVIDENCE_COUNT`：证据目标条数

---

## 隐私与安全

- `.gitignore` 默认排除 `data/`、`library/`、`.cursor/` 等本地运行数据
- API Key 保存在本地 `data/ui_history.json`（明文），请做好本机安全
- 不要把私密资料和密钥提交到远程仓库

---

## 当前迭代重点

- 更低回退率（减少“AI 返回无法解析”）
- 更高结构稳定性（字段完整、少重复、可执行）
- 更快响应（减少上下文负载与无效重试）
