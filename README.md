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

### 5 分钟快速开始

如果你是第一次接触这个项目，建议先按这条最短路径验证服务能否启动：

```bash
git clone https://github.com/finnyuan9527/dingbridge.git
cd dingbridge
cp .env.example .env
# 编辑 .env，至少补齐 DingTalk / OIDC 基础配置
# 临时联调可先设置 SECURITY__ALLOW_EPHEMERAL_KEYS=true
# Docker 默认把 SQLite 数据放在 Compose volume 的 /data；正式部署建议改成 MySQL
docker pull ghcr.io/finnyuan9527/dingbridge:latest
docker compose run --rm app alembic upgrade head
docker compose up -d
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/.well-known/openid-configuration
```

如果你要做正式部署，请继续看下面的“推荐部署步骤”和“签名密钥”说明。

### 部署建议

生产或联调环境默认推荐直接使用 GitHub Actions 发布的 Docker 镜像启动：

```bash
git clone https://github.com/finnyuan9527/dingbridge.git
cd dingbridge
cp .env.example .env
docker pull ghcr.io/finnyuan9527/dingbridge:latest
docker compose run --rm app alembic upgrade head
docker compose up -d
```

仓库内的 [docker-compose.yml](docker-compose.yml) 会从 `.env` 读取 `DINGBRIDGE_IMAGE` 作为应用镜像，并自动把 `REDIS__HOST` 指向 Compose 内的 `redis` 服务。

当前仓库的 `.env.example` 默认已经把 `DINGBRIDGE_IMAGE` 指向 `ghcr.io/finnyuan9527/dingbridge:latest`，所以首次部署按文档执行即可。

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

# 数据库
# Docker 默认使用持久化 SQLite volume，适合单机试用
DATABASE__URL=sqlite:////data/dingbridge.sqlite3
# 生产推荐 MySQL
# DATABASE__URL=mysql+pymysql://dingbridge:change_me@mysql:3306/dingbridge?charset=utf8mb4

# 管理接口密钥
SECURITY__ADMIN_API_KEY=replace_with_a_strong_admin_key

# 本地/临时联调：可先开启进程内临时密钥
SECURITY__ALLOW_EPHEMERAL_KEYS=true
```

4. 配置签名密钥。

联调或本地验证时，可直接保留：

```env
SECURITY__ALLOW_EPHEMERAL_KEYS=true
```

正式部署时，建议使用稳定 RSA 私钥，并关闭临时密钥：

```env
SECURITY__JWT_PRIVATE_KEY_PATH=/app/certs/jwt_private.pem
SECURITY__JWT_PUBLIC_KEY_PATH=/app/certs/jwt_public.pem
SECURITY__ALLOW_EPHEMERAL_KEYS=false
```

如果你使用文件路径方式，需要把密钥挂载到容器内。例如可以新增一个 `docker-compose.override.yml`：

```yaml
services:
  app:
    volumes:
      - ./certs:/app/certs:ro
```

最小密钥生成命令示例：

```bash
mkdir -p certs
openssl genrsa -out certs/jwt_private.pem 2048
openssl rsa -in certs/jwt_private.pem -pubout -out certs/jwt_public.pem
```

5. 拉取镜像：

```bash
docker pull ghcr.io/finnyuan9527/dingbridge:latest
```

6. 初始化或升级数据库 schema：

```bash
docker compose run --rm app alembic upgrade head
```

默认 Docker 部署会把 SQLite 数据库存到 Compose 的 `dingbridge_data` volume 中，因此这一步的迁移结果会保留下来。正式部署仍然更推荐把 `DATABASE__URL` 指向外部 MySQL。

7. 启动服务：

```bash
docker compose up -d
```

8. 检查容器是否正常启动：

```bash
docker compose ps
docker compose logs -f app
```

9. 验证服务是否可访问：

```bash
curl http://127.0.0.1:8000/healthz
```

#### Admin Console 管理页

当前版本已经提供最小可用的 OIDC Client 管理页，适合在首次部署后快速创建或维护多个客户端配置。

访问地址：

- Docker/源码默认本地地址：`http://127.0.0.1:8000/admin/console/oidc-clients`
- 线上部署地址：`https://your-domain.example.com/admin/console/oidc-clients`

使用前提：

- `.env` 中必须设置 `SECURITY__ADMIN_API_KEY`
- 该页面本身不会建立独立登录态，而是由浏览器在页面内填写 `x-admin-key` 后调用 Admin API
- 因为管理页会直接操作 `/admin/oidc-clients` 和 `/admin/dingtalk-apps`，建议只在受信任内网、堡垒机或受限反向代理后暴露

推荐使用步骤：

1. 打开 `/admin/console/oidc-clients`
2. 在 `Admin API Key` 输入框填入 `SECURITY__ADMIN_API_KEY`
3. 点击 `Load Clients`，加载当前 OIDC Client 列表和 DingTalk App 列表
4. 如需新增客户端，点击 `New Client`
5. 填写 `client_id`、`name`、`redirect_uris`
6. 首次创建时必须填写 `client_secret`
7. 如需绑定指定钉钉应用，可选择 `dingtalk_app_id`
8. 点击 `Save Client`

当前管理页行为说明：

- 支持列出已有 OIDC Client
- 支持新建客户端
- 支持编辑 `name`、`enabled`、`redirect_uris`、`dingtalk_app_id`
- 更新已有客户端时，`client_secret` 留空表示保持原值不变
- 当前版本不会回显已有 `client_secret`
- 当前版本不提供删除按钮；如需删除能力，建议后续配合审计和权限控制单独设计
- 当前页面只管理 OIDC Client；DingTalk App 仍通过 Admin API 管理

#### 审计日志

当前版本会把以下安全相关事件持久化到数据库表 `audit_logs`：

- `login_success`
- `login_failure`
- `token_issued`

这些事件在落库的同时仍保留标准 logger 输出。当前版本还没有提供审计日志查询页面或查询 API，如需排查，可直接查询数据库，例如：

```sql
SELECT id, event, client_id, user_sub, created_at
FROM audit_logs
ORDER BY id DESC
LIMIT 20;
```

如果使用默认 Docker SQLite 部署，数据库文件位于应用容器的 `/data/dingbridge.sqlite3`。如果使用 MySQL，请使用对应 MySQL 客户端连接 `DATABASE__URL` 指向的数据库查询。

#### 使用 oidcdebugger.com 联调

如果你想通过 `https://oidcdebugger.com/` 验证当前 OIDC 流程，先确认服务端客户端配置允许对应回调地址：

- 不要直接使用生产或正式环境里的 confidential client；建议单独创建一次性测试 client
- `client_id` 使用当前已注册的测试客户端
- `redirect_uri` 必须已经加入该客户端的白名单
- 如果你要用 `https://oidcdebugger.com/debug`，需要先把它加入 `redirect_uris`

如果你还没有测试 client，可以通过管理接口创建一个一次性联调用客户端：

```bash
curl -X POST 'https://your-domain.example.com/admin/oidc-clients' \
  -H 'Content-Type: application/json' \
  -H 'x-admin-key: your-admin-key' \
  -d '{
    "client_id": "oidcdebugger-test",
    "name": "OIDC Debugger Test",
    "enabled": true,
    "client_secret": "replace-with-a-temporary-secret",
    "redirect_uris": ["https://oidcdebugger.com/debug"]
  }'
```

推荐填写：

- `Authorize URI`: `https://your-domain.example.com/oidc/authorize`
- `Access Token URI`: `https://your-domain.example.com/oidc/token`
- `Client ID`: 测试客户端的 `client_id`
- `Client Secret`: 仅填写该测试客户端的 `client_secret`
- `Scope`: `openid`
- `Response Type`: `code`
- `Redirect URI`: 已注册的回调地址，例如 `https://oidcdebugger.com/debug`
- `State`: 任意随机值
- `Nonce`: 任意随机值
- `PKCE`: 开启
- `Code Challenge Method`: `S256`

注意事项：

- 不要把生产环境 client secret 或长期使用的 secret 输入第三方网站；联调结束后应删除测试 client 或轮换其 secret
- 当前实现强制要求 PKCE；如果缺少 `code_challenge` 或 `code_challenge_method` 不是 `S256`，`/oidc/authorize` 会直接返回 `400`
- `redirect_uri` 只要不在客户端白名单内，就会返回 `invalid_redirect_uri`
- 目前更稳妥的联调方式是使用默认 query redirect 流程；如果第三方工具强依赖 `response_mode=form_post`，需要额外确认兼容性

#### OIDC 联调注意事项

- Authorization Code 只能使用一次；同一个 `code` 第二次调用 `/oidc/token` 会返回 `invalid_grant`
- Authorization Code 默认有效期为 60 秒；拿到 `code` 后应尽快交换 token
- `/oidc/token` 中的 `redirect_uri` 必须和 `/oidc/authorize` 阶段使用的值完全一致
- 如果授权阶段启用了 PKCE，`/oidc/token` 中的 `code_verifier` 必须与当时生成 `code_challenge` 的原始值完全一致
- 如果使用第三方调试器，请不要再手工调用 `/oidc/token` 混用同一轮 `code`
- 当前实现更适合标准 query redirect 调试；`response_mode=form_post` 兼容性建议单独验证

#### 常见错误与排查

- `invalid_grant`
  - 常见原因：`code` 已被消费、`code` 已过期、`redirect_uri` 不一致、`code_verifier` 不匹配
- `invalid_redirect_uri`
  - 当前 `redirect_uri` 不在客户端白名单中，或与注册值不完全一致
- `invalid_client_secret`
  - `client_id` / `client_secret` 组合不正确
- `missing SECURITY__JWT_PRIVATE_KEY or SECURITY__JWT_PRIVATE_KEY_PATH`
  - 在 `SECURITY__ALLOW_EPHEMERAL_KEYS=false` 时未提供签名私钥
- `database schema is not initialized`
  - 数据库还没有执行迁移；源码启动执行 `alembic upgrade head`，Docker 部署执行 `docker compose run --rm app alembic upgrade head`
- `401 Unauthorized` on `/oidc/token`
  - 通常表示客户端认证失败，应检查 Basic Auth 或表单中的 `client_id` / `client_secret`

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
docker compose run --rm app alembic upgrade head
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
REDIS__PASSWORD=dingbridge_redis_password

DATABASE__URL=sqlite:///./dingbridge.sqlite3

SECURITY__ALLOW_EPHEMERAL_KEYS=true
```

公开部署必须注入稳定 RSA 私钥，不要使用临时密钥。

如果源码启动时准备接 MySQL，把 `DATABASE__URL` 改成例如 `mysql+pymysql://dingbridge:change_me@127.0.0.1:3306/dingbridge?charset=utf8mb4`。

#### 3. 启动依赖服务

```bash
docker compose up -d redis
```

#### 4. 初始化或升级数据库 schema

```bash
alembic upgrade head
```

#### 5. 启动 DingBridge

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
DINGBRIDGE_IMAGE=dingbridge:latest docker compose run --rm app alembic upgrade head
DINGBRIDGE_IMAGE=dingbridge:latest docker compose up -d
```

部署前请确认：

- 使用 HTTPS 反向代理
- 配置稳定 RSA 私钥
- 配置安全的 Redis 密码
- 设置 `SECURITY__ADMIN_API_KEY`
- 不把 `.env`、`certs/` 提交到仓库

### 主要端点

OIDC:

- `GET /.well-known/openid-configuration`：OIDC Discovery 文档
- `GET /oidc/authorize`：Authorization Code 授权入口
- `POST /oidc/token`：交换 access token / id token / refresh token
- `GET /oidc/userinfo`：读取当前 access token 对应的用户信息
- `GET /oidc/jwks.json`：提供 JWT 验签所需的公钥
- `GET /oidc/logout`：发起前端登出流程
- `POST /oidc/logout`：执行后端登出与 refresh token 失效

DingTalk:

- `GET /dingtalk/login`：跳转钉钉 OAuth 登录
- `GET /dingtalk/callback`：接收钉钉登录回调

Admin:

- `GET /admin/idp-settings`：读取当前 IdP 配置，需 `x-admin-key`
- `PUT /admin/idp-settings`：更新当前 IdP 配置，需 `x-admin-key`
- `GET /admin/dingtalk-apps`：列出钉钉应用配置，需 `x-admin-key`
- `POST /admin/dingtalk-apps`：创建或更新钉钉应用配置，需 `x-admin-key`
- `GET /admin/console/oidc-clients`：OIDC Client 管理页
- `GET /admin/oidc-clients`：列出 OIDC 客户端配置，需 `x-admin-key`
- `POST /admin/oidc-clients`：创建或更新 OIDC 客户端配置，需 `x-admin-key`
- `POST /admin/reload`：刷新运行时配置缓存，需 `x-admin-key`

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
- 构建并推送 Docker 镜像到 `ghcr.io/<repository-owner>/dingbridge`
- 更新该仓库命名空间下的 `latest` 镜像标签

本仓库的官方镜像地址是 `ghcr.io/finnyuan9527/dingbridge`。如果你在 fork 或组织仓库中发布，镜像地址会使用对应的 repository owner。

### 项目结构

```text
alembic/        Database schema migrations
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

### 5-Minute Quick Start

If you are new to the project, use this shortest path first to verify the service can start:

```bash
git clone https://github.com/finnyuan9527/dingbridge.git
cd dingbridge
cp .env.example .env
# Edit .env and fill in the basic DingTalk / OIDC settings
# For temporary local validation, you can start with SECURITY__ALLOW_EPHEMERAL_KEYS=true
# Docker stores the default SQLite database in the Compose volume at /data; for production, prefer MySQL
docker pull ghcr.io/finnyuan9527/dingbridge:latest
docker compose run --rm app alembic upgrade head
docker compose up -d
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/.well-known/openid-configuration
```

For production deployment, continue with the detailed steps and signing key guidance below.

### Deployment Recommendation

For production or shared testing environments, the default recommendation is to run the published Docker image from GitHub Actions:

```bash
git clone https://github.com/finnyuan9527/dingbridge.git
cd dingbridge
cp .env.example .env
docker pull ghcr.io/finnyuan9527/dingbridge:latest
docker compose run --rm app alembic upgrade head
docker compose up -d
```

The repository [docker-compose.yml](docker-compose.yml) reads `DINGBRIDGE_IMAGE` from `.env` for the application container and points `REDIS__HOST` to the Compose-managed `redis` service automatically.

In this repository, `.env.example` already points `DINGBRIDGE_IMAGE` to `ghcr.io/finnyuan9527/dingbridge:latest`, so the first-time deployment steps work as written.

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

# Database
# Docker defaults to persistent SQLite in a named volume for single-node deployments
DATABASE__URL=sqlite:////data/dingbridge.sqlite3
# MySQL is recommended for production
# DATABASE__URL=mysql+pymysql://dingbridge:change_me@mysql:3306/dingbridge?charset=utf8mb4

# Admin API key
SECURITY__ADMIN_API_KEY=replace_with_a_strong_admin_key

# Local or temporary validation can start with ephemeral keys
SECURITY__ALLOW_EPHEMERAL_KEYS=true
```

4. Configure signing keys.

For local or temporary debugging, you can keep:

```env
SECURITY__ALLOW_EPHEMERAL_KEYS=true
```

For production, use a stable RSA key pair and disable ephemeral keys:

```env
SECURITY__JWT_PRIVATE_KEY_PATH=/app/certs/jwt_private.pem
SECURITY__JWT_PUBLIC_KEY_PATH=/app/certs/jwt_public.pem
SECURITY__ALLOW_EPHEMERAL_KEYS=false
```

If you use file paths, make sure the key files are mounted into the container. For example, create a `docker-compose.override.yml`:

```yaml
services:
  app:
    volumes:
      - ./certs:/app/certs:ro
```

Minimal key generation example:

```bash
mkdir -p certs
openssl genrsa -out certs/jwt_private.pem 2048
openssl rsa -in certs/jwt_private.pem -pubout -out certs/jwt_public.pem
```

5. Pull the image:

```bash
docker pull ghcr.io/finnyuan9527/dingbridge:latest
```

6. Initialize or upgrade the database schema:

```bash
docker compose run --rm app alembic upgrade head
```

The default Docker setup stores the SQLite database in the Compose `dingbridge_data` volume, so the migration result persists across container restarts. For production, it is still better to point `DATABASE__URL` at an external MySQL instance.

7. Start the stack:

```bash
docker compose up -d
```

8. Check whether the containers are healthy:

```bash
docker compose ps
docker compose logs -f app
```

9. Verify the application is reachable:

```bash
curl http://127.0.0.1:8000/healthz
```

#### Admin Console

The current version includes a minimal OIDC Client admin page so you can create and maintain multiple client configurations after the service is up.

Access URL:

- Local default address for Docker or source startup: `http://127.0.0.1:8000/admin/console/oidc-clients`
- Public deployment address: `https://your-domain.example.com/admin/console/oidc-clients`

Prerequisites:

- `SECURITY__ADMIN_API_KEY` must be set in `.env`
- The page does not create a separate login session. Instead, you enter `x-admin-key` in the page and the browser calls the Admin APIs directly
- Because the page operates on `/admin/oidc-clients` and `/admin/dingtalk-apps`, expose it only behind a trusted internal network, bastion host, or restricted reverse proxy

Recommended flow:

1. Open `/admin/console/oidc-clients`
2. Paste `SECURITY__ADMIN_API_KEY` into the `Admin API Key` field
3. Click `Load Clients` to fetch the current OIDC client list and DingTalk app list
4. Click `New Client` if you want to create a new client
5. Fill in `client_id`, `name`, and `redirect_uris`
6. `client_secret` is required when creating a client for the first time
7. Select `dingtalk_app_id` if you want to bind the client to a specific DingTalk app
8. Click `Save Client`

Current behavior:

- lists existing OIDC clients
- creates new clients
- edits `name`, `enabled`, `redirect_uris`, and `dingtalk_app_id`
- keeps the existing secret unchanged when `client_secret` is left blank during updates
- never shows the stored `client_secret`
- does not provide delete actions yet; deletion should be designed later with audit and permission controls
- currently manages OIDC clients only; DingTalk apps are still managed through the Admin APIs

#### Audit Logs

The current version persists these security-relevant events into the `audit_logs` table:

- `login_success`
- `login_failure`
- `token_issued`

These events are still emitted to the normal logger as well. There is no audit log UI or query API yet, so for now you should inspect the database directly, for example:

```sql
SELECT id, event, client_id, user_sub, created_at
FROM audit_logs
ORDER BY id DESC
LIMIT 20;
```

With the default Docker SQLite deployment, the database file is `/data/dingbridge.sqlite3` inside the application container. If you use MySQL, query the database pointed to by `DATABASE__URL` with your MySQL client.

#### Testing With oidcdebugger.com

If you want to validate the current OIDC flow with `https://oidcdebugger.com/`, make sure the server-side client configuration allows the redirect URI first:

- do not use a production or long-lived confidential client; create a disposable test client for debugger-based validation
- use a registered test `client_id`
- the `redirect_uri` must already be in that client's allowlist
- if you want to use `https://oidcdebugger.com/debug`, add it to the client's `redirect_uris` first

If you do not have a dedicated test client yet, you can create a disposable one through the admin API:

```bash
curl -X POST 'https://your-domain.example.com/admin/oidc-clients' \
  -H 'Content-Type: application/json' \
  -H 'x-admin-key: your-admin-key' \
  -d '{
    "client_id": "oidcdebugger-test",
    "name": "OIDC Debugger Test",
    "enabled": true,
    "client_secret": "replace-with-a-temporary-secret",
    "redirect_uris": ["https://oidcdebugger.com/debug"]
  }'
```

Recommended values:

- `Authorize URI`: `https://your-domain.example.com/oidc/authorize`
- `Access Token URI`: `https://your-domain.example.com/oidc/token`
- `Client ID`: the test client's `client_id`
- `Client Secret`: only the `client_secret` of that disposable test client
- `Scope`: `openid`
- `Response Type`: `code`
- `Redirect URI`: a registered callback such as `https://oidcdebugger.com/debug`
- `State`: any random value
- `Nonce`: any random value
- `PKCE`: enabled
- `Code Challenge Method`: `S256`

Notes:

- never paste a production client secret or any long-lived secret into a third-party site; after testing, delete the disposable client or rotate its secret
- the current implementation requires PKCE; if `code_challenge` is missing or `code_challenge_method` is not `S256`, `/oidc/authorize` returns `400`
- if the `redirect_uri` is not in the client allowlist, the server returns `invalid_redirect_uri`
- the safest interop path right now is the default query redirect flow; if a third-party debugger strictly requires `response_mode=form_post`, verify compatibility separately

#### OIDC Debugging Notes

- an authorization code is single-use; reusing the same `code` on `/oidc/token` returns `invalid_grant`
- authorization codes expire after 60 seconds by default, so exchange them quickly
- the `redirect_uri` sent to `/oidc/token` must exactly match the one used during `/oidc/authorize`
- if PKCE was used during authorization, the `code_verifier` on `/oidc/token` must exactly match the original value used to derive the `code_challenge`
- when using a third-party debugger, do not also manually call `/oidc/token` with the same authorization code
- the current implementation is better suited to standard query redirect debugging; verify `response_mode=form_post` compatibility separately if you depend on it

#### Common Errors And Troubleshooting

- `invalid_grant`
  - common causes: the `code` was already consumed, the `code` expired, the `redirect_uri` does not match, or the `code_verifier` is wrong
- `invalid_redirect_uri`
  - the current `redirect_uri` is not in the client allowlist or does not exactly match the registered value
- `invalid_client_secret`
  - the `client_id` / `client_secret` pair is incorrect
- `missing SECURITY__JWT_PRIVATE_KEY or SECURITY__JWT_PRIVATE_KEY_PATH`
  - a signing private key is required when `SECURITY__ALLOW_EPHEMERAL_KEYS=false`
- `database schema is not initialized`
  - the database has not been migrated yet; run `alembic upgrade head` for source startup, or `docker compose run --rm app alembic upgrade head` for Docker deployment
- `401 Unauthorized` on `/oidc/token`
  - usually indicates failed client authentication; check Basic Auth or the submitted `client_id` / `client_secret`

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
docker compose run --rm app alembic upgrade head
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
REDIS__PASSWORD=dingbridge_redis_password

DATABASE__URL=sqlite:///./dingbridge.sqlite3

SECURITY__ALLOW_EPHEMERAL_KEYS=true
```

Public deployments must use a stable RSA private key. Do not use ephemeral keys for deployed services.

If you want to run from source with MySQL instead of local SQLite, replace `DATABASE__URL` with a DSN such as `mysql+pymysql://dingbridge:change_me@127.0.0.1:3306/dingbridge?charset=utf8mb4`.

#### 3. Start Redis

```bash
docker compose up -d redis
```

#### 4. Initialize or upgrade the database schema

```bash
alembic upgrade head
```

#### 5. Start DingBridge

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
DINGBRIDGE_IMAGE=dingbridge:latest docker compose run --rm app alembic upgrade head
DINGBRIDGE_IMAGE=dingbridge:latest docker compose up -d
```

Before deployment, make sure to:

- Put DingBridge behind HTTPS
- Provide a stable RSA private key
- Use a strong Redis password
- Set `SECURITY__ADMIN_API_KEY`
- Never commit `.env` or `certs/`

### Endpoints

OIDC:

- `GET /.well-known/openid-configuration`: OIDC discovery document
- `GET /oidc/authorize`: authorization entrypoint for the Authorization Code flow
- `POST /oidc/token`: exchange authorization codes or refresh tokens for tokens
- `GET /oidc/userinfo`: retrieve user claims for the current access token
- `GET /oidc/jwks.json`: publish public keys for JWT verification
- `GET /oidc/logout`: initiate front-channel logout
- `POST /oidc/logout`: perform logout and revoke refresh-token-backed sessions

DingTalk:

- `GET /dingtalk/login`: redirect the browser to DingTalk OAuth
- `GET /dingtalk/callback`: receive the DingTalk OAuth callback

Admin:

- `GET /admin/idp-settings`: read current IdP settings, requires `x-admin-key`
- `PUT /admin/idp-settings`: update current IdP settings, requires `x-admin-key`
- `GET /admin/dingtalk-apps`: list DingTalk app configs, requires `x-admin-key`
- `POST /admin/dingtalk-apps`: create or update DingTalk app configs, requires `x-admin-key`
- `GET /admin/console/oidc-clients`: OIDC client admin page
- `GET /admin/oidc-clients`: list OIDC client configs, requires `x-admin-key`
- `POST /admin/oidc-clients`: create or update OIDC client configs, requires `x-admin-key`
- `POST /admin/reload`: refresh runtime config caches, requires `x-admin-key`

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
- build and push the Docker image to `ghcr.io/<repository-owner>/dingbridge`
- refresh the `latest` image tag in that repository namespace

The official image for this repository is `ghcr.io/finnyuan9527/dingbridge`. Forks and organization repositories publish under their own repository owner.

### Project Structure

```text
alembic/        Database schema migrations
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

- Add deployment and monitoring examples

### Contributing

Issues and pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and run the test suite before submitting changes.

### Security

Do not disclose secrets, tokens, real user data, or internal domains in public issues. See [SECURITY.md](SECURITY.md).

### License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
