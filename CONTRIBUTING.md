# Contributing to DingBridge

## 中文

感谢你愿意参与 DingBridge。提交 issue 或 pull request 前，请确认：

- 不提交 `.env`、`certs/`、私钥、token 或真实用户信息。
- 变更保持 OIDC-only 方向，不重新引入 SAML 流程。
- 代码改动尽量包含测试。
- 提交前运行：

```bash
python3 -m pytest -q
```

### 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-test.txt
cp .env.example .env
docker compose up -d redis
uvicorn app.main:app --reload
```

### Pull Request 建议

- 描述变更目标和主要实现。
- 列出测试命令和结果。
- 对配置、部署或安全行为变化做明确说明。

## English

Thank you for contributing to DingBridge. Before opening an issue or pull request, please make sure:

- Do not commit `.env`, `certs/`, private keys, tokens, or real user data.
- Keep the project OIDC-only. Do not reintroduce SAML flows.
- Include tests for code changes when practical.
- Run the test suite before submitting:

```bash
python3 -m pytest -q
```

### Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-test.txt
cp .env.example .env
docker compose up -d redis
uvicorn app.main:app --reload
```

### Pull Request Checklist

- Explain the goal and implementation.
- Include the test command and result.
- Call out configuration, deployment, or security behavior changes.
