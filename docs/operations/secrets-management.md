# 密钥托管规范

## 原则

- 不在仓库提交任何真实密钥
- 生产密钥仅通过环境变量注入
- 本地调试使用 `.env`，并确保 `.gitignore` 覆盖

## 必要变量

- `OPENAI_API_KEY`（或兼容网关的密钥变量）
- `HEGEL_ENV`
- 其他敏感配置（数据库、代理）

## 最小实践

- CI 使用 GitHub Actions Secrets
- 按环境拆分 secret（dev/staging/prod）
- 密钥轮换周期建议 30-90 天
