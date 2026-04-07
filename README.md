# Hegelian-dialectics

**EN:** A small Streamlit app that analyzes everyday questions in a Hegelian dialectic style: thesis / antithesis / contradiction / synthesis, next step, and an actionable plan, with optional RAG over your local texts.

**中文：** 基于黑格尔辩证结构的对话分析工具：拆解问题、矛盾与扬弃方向，并给出可执行计划；可接入本地资料库做检索增强。

---

## 功能概要

- 辩证结构化输出（含启发式原文参照、通俗化说明等）
- 本地资料库：多种文本格式、索引与检索、在界面中管理
- 支持 OpenAI 兼容 API（如方舟/豆包等）；流式输出与简单缓存
- Windows 下一键启动脚本（Conda / Python 检测、依赖与端口）

---

## 目录结构（简要）

```text
.
├─ app_streamlit.py          # Web 界面
├─ hegel_engine.py           # 分析引擎与模型调用
├─ knowledge_base.py         # 资料抽取与检索
├─ start-hegel-app.ps1       # 启动逻辑
├─ 一键启动-黑格尔对话机.bat   # Windows 入口
├─ requirements.txt
├─ data/                     # 运行时索引与缓存（默认不入库）
├─ uploads/                  # 用户上传（默认不入库）
└─ hegel-books/              # 本地书籍目录（默认不入库）
```

---

## 技术栈（一览）

Python 3.10+ · Streamlit · requests（OpenAI 兼容 HTTP）· 本地 JSON 索引与分块检索 · PowerShell/Batch 启动脚本

---

## 快速运行

**Windows：** 双击 `一键启动-黑格尔对话机.bat`，按提示安装依赖并访问浏览器中的本地地址（默认端口 8501）。

**命令行：**

```bash
pip install -r requirements.txt
streamlit run app_streamlit.py
```

首次使用请在界面中配置 API，并将资料放入 `hegel-books/`（或走上传），再执行同步/重建索引。

---

## 可调参数

与超时、重试、缓存等相关环境变量可在 `hegel_engine.py` 顶部附近查看（`HEGEL_*` / `LLM_*` 等）；按需设置即可，日常可不改。

---

## 仓库与隐私

代码提交时通过 `.gitignore` 排除资料正文、本地 `data/`、`uploads/` 等，避免 API  key 与私人问题进入 Git。请自行保管密钥与书籍文件。
