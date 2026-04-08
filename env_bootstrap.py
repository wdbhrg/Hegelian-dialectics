from __future__ import annotations

import os
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        # 环境加载失败不阻断主流程
        pass


def bootstrap_env() -> None:
    # 优先：项目根目录 .env（本地覆写）
    _load_env_file(Path(".env"))
    env_name = os.environ.get("HEGEL_ENV", "development").strip().lower() or "development"
    # 次优先：按环境分层配置（不覆盖已存在变量）
    _load_env_file(Path("config") / "environments" / f"{env_name}.env")

