# DingBridge

> 钉钉到 OIDC 的企业 SSO 身份桥接服务。
> An enterprise SSO identity bridge from DingTalk to OIDC.

[中文](#中文) | [English](#english)

---

## 中文

### 项目简介

DingBridge 是一个轻量级企业 SSO 身份桥接服务，以钉钉 DingTalk 作为企业身份源，对外提供标准 OIDC Provider 能力。它适合把只支持标准 OIDC 的 SaaS 或内部系统接入钉钉身份体系，例如 Volcengine Coze、内部管理后台、BI 平台等。

当前项目聚焦 OIDC，不包含 SAML 流程。

### 功能特性

- 钉钉 OAuth 登录和回调处理
- OIDC Discovery、Authorization Code、Token、UserInfo、JWKS
- PKCE S256 校验
- Refresh token 轮换和撤销
- 浏览器会话 Cookie 管理
- 多 OIDC Client 和多钉钉应用动态配置
- 管理接口支持运行时配置刷新
- Redis 存储 session、authorization code、refresh token 和钉钉 access token 缓存
- SQLAlchemy 存储动态配置

### 架构概览

```text
SaaS / Internal App
        |
        | OIDC redirect
        v
    DingBridge
        |
        | DingTalk OAuth
        v
      DingTalk
```

核心流程：

1. 用户访问接入方应用。
2. 应用将用户重定向到 DingBridge 的 `/oidc/authorize`。
3. DingBridge 检查本地 SSO session；无 session 时跳转钉钉登录。
4. 钉钉回调后，DingBridge 映射用户信息为 OIDC claims。
5. DingBridge 颁发 authorization code、access token、ID token 和 refresh token。

### 技术栈

- Python 3.12+
- FastAPI
- Uvicorn
- python-jose
- httpx
- Redis
- SQLAlchemy
- Pydantic Settings

### 部署建议

生产或联调环境默认推荐直接使用 GitHub Actions 发布的 Docker 镜像启动：

```bash
git clone https://github.com/finnyuan9527/dingbridge.git
cd dingbridge
cp .env.example .env
docker pull ghcr.io/finnyuan9527/dingbridge:latest
docker compose up -d
```

仓库内的 [docker-compose.yml](docker-compose.yml) 会从 `.env` 读取 `DINGBRIDGE_IMAGE` 作为应用镜像，并自动把 `REDIS__HOST` 指向 Compose 内的 `redis` 服务。

如果你在 fork、镜像仓库迁移或组织镜像命名空间下部署，请把 `.env` 里的 `DINGBRIDGE_IMAGE` 改成你自己的发布地址，例如 `ghcr.io/<your-owner>/dingbridge:latest`。

源码启动和源码构建镜像仍然支持，但默认建议优先使用上面的已发布镜像。

#### 推荐部署步骤

1. 首次部署时先拉取仓库代码：

```bash
git clone https://github.com/finnyuan9527/dingbridge.git
cd dingbridge
```

2. 复制环境变量模板：

```bash
cp .env.example .env
```

3. 编辑 `.env`，至少确认这些字段：

```env
# 发布镜像地址
DINGBRIDGE_IMAGE=ghcr.io/finnyuan9527/dingbridge:latest

# 钉钉应用
DINGTALK__APP_KEY=your_app_key
DINGTALK__APP_SECRET=your_app_secret
DINGTALK__CALLBACK_URL=https://your-domain.example.com/dingtalk/callback

# 对外 OIDC 地址
OIDC__ISSUER=https://your-domain.example.com
OIDC__CLIENT_ID=your-client-id
OIDC__CLIENT_SECRET=your-client-secret
OIDC__REDIRECT_URI=https://your-app.example.com/oidc/callback

# Redis 密码
REDIS__PASSWORD=replace_with_a_strong_password

# 管理接口密钥
SECURITY__ADMIN_API_KEY=replace_with_a_strong_admin_key

# 生产环境必须注入稳定 RSA 私钥
SECURITY__JWT_PRIVATE_KEY_PATH=/app/certs/jwt_private.pem
SECURITY__JWT_PUBLIC_KEY_PATH=/app/certs/jwt_public.pem
SECURITY__ALLOW_EPHEMERAL_KEYS=false
```

4. 准备好 RSA 密钥文件，并确保容器内路径与 `.env` 一致。

5. 拉取镜像并启动服务：

```bash
docker pull ghcr.io/finnyuan9527/dingbridge:latest
docker compose up -d
```

6. 检查容器是否正常启动：

```bash
docker compose ps
docker compose logs -f app
```

7. 验证服务是否可访问：

```bash
curl http://127.0.0.1:8000/healthz
```

如果你前面有反向代理和 HTTPS，对外还需要额外确认：

- `OIDC__ISSUER` 与外部访问域名完全一致
- `DINGTALK__CALLBACK_URL` 已配置到钉钉应用后台
- 反向代理已透传 `Host` 和 `X-Forwarded-Proto`
- 8000 端口只暴露给反向代理或内网，不直接公网裸露

#### 升级已有部署到新版本镜像

如果你本地已经有这个仓库，只是要更新到 GitHub Actions 发布的新镜像，可直接执行：

```bash
git pull
docker pull ghcr.io/finnyuan9527/dingbridge:latest
docker compose up -d
```

如果你要固定到某个发布版本，也可以把 `.env` 中的 `DINGBRIDGE_IMAGE` 改成 tag 版，例如：

```env
DINGBRIDGE_IMAGE=ghcr.io/finnyuan9527/dingbridge:v0.1.0
```

### 源码启动

#### 1. 准备环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

测试依赖：

```bash
pip install -r requirements-test.txt
```

#### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少配置：

```env
DINGTALK__APP_KEY=your_app_key
DINGTALK__APP_SECRET=your_app_secret
DINGTALK__CALLBACK_URL=http://localhost:8000/dingtalk/callback

OIDC__ISSUER=http://localhost:8000
OIDC__CLIENT_ID=coze-client-id
OIDC__CLIENT_SECRET=coze-client-secret
OIDC__REDIRECT_URI=https://coze.example.com/oidc/callback

REDIS__HOST=127.0.0.1
REDIS__PORT=6379
REDIS__PASSWORD=

SECURITY__ALLOW_EPHEMERAL_KEYS=true
```

公开部署必须注入稳定 RSA 私钥，不要使用临时密钥。

#### 3. 启动依赖服务

```bash
docker compose up -d redis
```

#### 4. 启动 DingBridge

```bash
uvicorn app.main:app --reload
```

服务启动后访问：

- Health check: `http://127.0.0.1:8000/healthz`
- API docs: `http://127.0.0.1:8000/docs`
- OIDC discovery: `http://127.0.0.1:8000/.well-known/openid-configuration`

### 源码构建 Docker 镜像

如果你希望基于当前仓库源码自行构建镜像，可以执行：

```bash
cp .env.example .env
docker build -t dingbridge:latest .
docker compose up -d
```

部署前请确认：

- 使用 HTTPS 反向代理
- 配置稳定 RSA 私钥
- 配置安全的 Redis 密码
- 设置 `SECURITY__ADMIN_API_KEY`
- 不把 `.env`、`certs/` 提交到仓库

### 主要端点

OIDC:

- `GET /.well-known/openid-configuration`
- `GET /oidc/authorize`
- `POST /oidc/token`
- `GET /oidc/userinfo`
- `GET /oidc/jwks.json`
- `GET /oidc/logout`
- `POST /oidc/logout`

DingTalk:

- `GET /dingtalk/login`
- `GET /dingtalk/callback`

Admin:

- `GET /admin/idp-settings`
- `PUT /admin/idp-settings`
- `GET /admin/dingtalk-apps`
- `POST /admin/dingtalk-apps`
- `GET /admin/oidc-clients`
- `POST /admin/oidc-clients`
- `POST /admin/reload`

### 测试

```bash
python3 -m pytest -q
```

GitHub Actions 会在 `main` 分支推送和 pull request 时运行同一套测试。

发布方式：

```bash
git tag v0.1.0
git push origin v0.1.0
```

推送 `v*` tag 后，GitHub Actions 会：

- 创建 GitHub Release（源码归档由 GitHub 自动附带）
- 构建并推送 Docker 镜像到 `ghcr.io/finnyuan9527/dingbridge`
- 更新推荐部署镜像标签 `ghcr.io/finnyuan9527/dingbridge:latest`

### 项目结构

```text
app/
  routers/      HTTP routes for OIDC, DingTalk, and admin APIs
  services/     Authentication, token, session, config, and DingTalk logic
  db/           SQLAlchemy models and session helpers
  models/       Pydantic domain models
  security/     Audit logging helpers
scripts/        Manual diagnostic tools
tests/          Automated tests
```

### 路线图

- 完善 OIDC 兼容性测试
- 增强钉钉组织和部门字段映射
- 增加配置迁移机制
- 增加结构化审计日志落库
- 增加部署和监控建议

### 贡献

欢迎 issue 和 pull request。提交前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并运行测试。

### 安全

请不要在 issue 中公开密钥、token、真实用户信息或内部域名。安全问题请参考 [SECURITY.md](SECURITY.md)。

### 许可证

本项目使用 MIT License，详见 [LICENSE](LICENSE)。

---

## English

### Overview

DingBridge is a lightweight enterprise SSO identity bridge. It uses DingTalk as the corporate identity source and exposes a standard OIDC Provider interface for SaaS products and internal systems, such as Volcengine Coze, admin portals, and BI platforms.

This project is focused on OIDC only. SAML flows are intentionally not included.

### Features

- DingTalk OAuth login and callback handling
- OIDC Discovery, Authorization Code, Token, UserInfo, and JWKS endpoints
- PKCE S256 validation
- Refresh token rotation and revocation
- Browser session cookie management
- Multiple OIDC clients and DingTalk apps through dynamic configuration
- Admin APIs for runtime configuration reloads
- Redis-backed sessions, authorization codes, refresh tokens, and DingTalk access token cache
- SQLAlchemy-backed dynamic configuration

### Architecture

```text
SaaS / Internal App
        |
        | OIDC redirect
        v
    DingBridge
        |
        | DingTalk OAuth
        v
      DingTalk
```

Flow:

1. A user opens a connected application.
2. The application redirects the user to `/oidc/authorize`.
3. DingBridge checks the local SSO session and redirects to DingTalk when needed.
4. After DingTalk redirects back, DingBridge maps DingTalk user data into OIDC claims.
5. DingBridge issues an authorization code, access token, ID token, and refresh token.

### Tech Stack

- Python 3.12+
- FastAPI
- Uvicorn
- python-jose
- httpx
- Redis
- SQLAlchemy
- Pydantic Settings

### Deployment Recommendation

For production or shared testing environments, the default recommendation is to run the published Docker image from GitHub Actions:

```bash
git clone https://github.com/finnyuan9527/dingbridge.git
cd dingbridge
cp .env.example .env
docker pull ghcr.io/finnyuan9527/dingbridge:latest
docker compose up -d
```

The repository [docker-compose.yml](docker-compose.yml) reads `DINGBRIDGE_IMAGE` from `.env` for the application container and points `REDIS__HOST` to the Compose-managed `redis` service automatically.

If you deploy from a fork, a mirror, or a different package namespace, update `DINGBRIDGE_IMAGE` in `.env` to your own published image, for example `ghcr.io/<your-owner>/dingbridge:latest`.

Source startup and source-built images are still supported, but the published image should be the default path.

#### Recommended Deployment Steps

1. For a first-time deployment, clone the repository first:

```bash
git clone https://github.com/finnyuan9527/dingbridge.git
cd dingbridge
```

2. Copy the environment template:

```bash
cp .env.example .env
```

3. Edit `.env` and make sure these values are set correctly:

```env
# Published image reference
DINGBRIDGE_IMAGE=ghcr.io/finnyuan9527/dingbridge:latest

# DingTalk app
DINGTALK__APP_KEY=your_app_key
DINGTALK__APP_SECRET=your_app_secret
DINGTALK__CALLBACK_URL=https://your-domain.example.com/dingtalk/callback

# Public OIDC endpoint
OIDC__ISSUER=https://your-domain.example.com
OIDC__CLIENT_ID=your-client-id
OIDC__CLIENT_SECRET=your-client-secret
OIDC__REDIRECT_URI=https://your-app.example.com/oidc/callback

# Redis password
REDIS__PASSWORD=replace_with_a_strong_password

# Admin API key
SECURITY__ADMIN_API_KEY=replace_with_a_strong_admin_key

# Production must use a stable RSA key pair
SECURITY__JWT_PRIVATE_KEY_PATH=/app/certs/jwt_private.pem
SECURITY__JWT_PUBLIC_KEY_PATH=/app/certs/jwt_public.pem
SECURITY__ALLOW_EPHEMERAL_KEYS=false
```

4. Prepare the RSA key files and make sure the paths inside the container match the values in `.env`.

5. Pull the image and start the stack:

```bash
docker pull ghcr.io/finnyuan9527/dingbridge:latest
docker compose up -d
```

6. Check whether the containers are healthy:

```bash
docker compose ps
docker compose logs -f app
```

7. Verify the application is reachable:

```bash
curl http://127.0.0.1:8000/healthz
```

If you deploy behind HTTPS and a reverse proxy, also verify:

- `OIDC__ISSUER` exactly matches the public domain
- `DINGTALK__CALLBACK_URL` is registered in the DingTalk app configuration
- the reverse proxy forwards `Host` and `X-Forwarded-Proto`
- port 8000 is only exposed to the proxy or a trusted internal network

#### Updating an Existing Deployment

If you already have the repository locally and just want to update to a newer image published by GitHub Actions:

```bash
git pull
docker pull ghcr.io/finnyuan9527/dingbridge:latest
docker compose up -d
```

If you want to pin a specific release image instead of `latest`, set `DINGBRIDGE_IMAGE` in `.env` to a version tag such as:

```env
DINGBRIDGE_IMAGE=ghcr.io/finnyuan9527/dingbridge:v0.1.0
```

### Run From Source

#### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Test dependencies:

```bash
pip install -r requirements-test.txt
```

#### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and configure at least:

```env
DINGTALK__APP_KEY=your_app_key
DINGTALK__APP_SECRET=your_app_secret
DINGTALK__CALLBACK_URL=http://localhost:8000/dingtalk/callback

OIDC__ISSUER=http://localhost:8000
OIDC__CLIENT_ID=coze-client-id
OIDC__CLIENT_SECRET=coze-client-secret
OIDC__REDIRECT_URI=https://coze.example.com/oidc/callback

REDIS__HOST=127.0.0.1
REDIS__PORT=6379
REDIS__PASSWORD=

SECURITY__ALLOW_EPHEMERAL_KEYS=true
```

Public deployments must use a stable RSA private key. Do not use ephemeral keys for deployed services.

#### 3. Start Redis

```bash
docker compose up -d redis
```

#### 4. Start DingBridge

```bash
uvicorn app.main:app --reload
```

Useful URLs:

- Health check: `http://127.0.0.1:8000/healthz`
- API docs: `http://127.0.0.1:8000/docs`
- OIDC discovery: `http://127.0.0.1:8000/.well-known/openid-configuration`

### Build a Docker Image From Source

If you prefer to build an image from the current source tree yourself:

```bash
cp .env.example .env
docker build -t dingbridge:latest .
docker compose up -d
```

Before deployment, make sure to:

- Put DingBridge behind HTTPS
- Provide a stable RSA private key
- Use a strong Redis password
- Set `SECURITY__ADMIN_API_KEY`
- Never commit `.env` or `certs/`

### Endpoints

OIDC:

- `GET /.well-known/openid-configuration`
- `GET /oidc/authorize`
- `POST /oidc/token`
- `GET /oidc/userinfo`
- `GET /oidc/jwks.json`
- `GET /oidc/logout`
- `POST /oidc/logout`

DingTalk:

- `GET /dingtalk/login`
- `GET /dingtalk/callback`

Admin:

- `GET /admin/idp-settings`
- `PUT /admin/idp-settings`
- `GET /admin/dingtalk-apps`
- `POST /admin/dingtalk-apps`
- `GET /admin/oidc-clients`
- `POST /admin/oidc-clients`
- `POST /admin/reload`

### Testing

```bash
python3 -m pytest -q
```

GitHub Actions runs the same test suite on pushes to `main` and on pull requests.

Release flow:

```bash
git tag v0.1.0
git push origin v0.1.0
```

When a `v*` tag is pushed, GitHub Actions will:

- create a GitHub Release, with source archives automatically provided by GitHub
- build and push the Docker image to `ghcr.io/finnyuan9527/dingbridge`
- refresh the recommended deployment tag `ghcr.io/finnyuan9527/dingbridge:latest`

### Project Structure

```text
app/
  routers/      HTTP routes for OIDC, DingTalk, and admin APIs
  services/     Authentication, token, session, config, and DingTalk logic
  db/           SQLAlchemy models and session helpers
  models/       Pydantic domain models
  security/     Audit logging helpers
scripts/        Manual diagnostic tools
tests/          Automated tests
```

### Roadmap

- Expand OIDC compatibility tests
- Improve DingTalk organization and department mappings
- Add database migration support
- Persist structured audit logs
- Add deployment and monitoring examples

### Contributing

Issues and pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and run the test suite before submitting changes.

### Security

Do not disclose secrets, tokens, real user data, or internal domains in public issues. See [SECURITY.md](SECURITY.md).

### License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
