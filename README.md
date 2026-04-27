# DingBridge (钉桥)

DingBridge 是一个企业级 SSO 身份桥接服务，旨在以**钉钉 (DingTalk)** 为唯一身份源，对外提供标准的 **OIDC (OpenID Connect)** 身份认证服务。

该项目的主要目标是帮助企业快速对接 **Volcengine Coze (扣子)** 及其他支持标准 SSO 协议的 SaaS 应用，实现统一身份认证与管理。

## 核心目标

*   **身份源统一**: 使用钉钉作为唯一的企业身份来源。
*   **协议标准化**: 对外暴露标准的 OIDC Provider 接口。
*   **应用对接**: 无缝集成 Coze 等企业级 SaaS 应用。

## 架构设计

### 总体思路

*   **对内**: 通过钉钉开放平台（企业内部应用/第三方应用）的 OAuth2 或扫码登录机制获取用户身份。
*   **对外**: 封装并转换身份信息，提供 OIDC 协议接口，充当 Identity Provider (IdP) 角色。

### 核心流程

1.  **用户访问应用**: 用户尝试访问 Coze 或其他受保护应用。
2.  **重定向**: 应用发现用户未登录，跳转至 DingBridge 的 OIDC 认证端点。
3.  **身份认证**: DingBridge 检查本地 Session；若无，则引导用户进行钉钉扫码或授权登录。
4.  **身份映射**: DingBridge 获取钉钉用户信息，并映射为标准 OIDC Claims。
5.  **返回凭证**: DingBridge 生成 ID Token，重定向回原应用完成登录。

## 核心功能模块

*   **API Gateway / Web 层**: 提供 `/oidc/*` 协议端点，管理 Web Session。
*   **认证编排 (Auth Orchestrator)**: 统一处理协议请求，路由至钉钉登录，并在登录后分发 Token/Assertion。
*   **钉钉适配 (DingTalk Adapter)**: 封装钉钉 API 调用（AccessToken, UserInfo, Department），屏蔽底层差异。
*   **用户与组织映射 (Identity Mapping)**: 灵活配置钉钉字段到 OIDC Claims 的映射规则。
*   **安全与审计**: 记录登录审计日志，敏感数据脱敏，支持 CSRF 防护。

## 技术栈

*   **语言**: Python 3.12+
*   **Web 框架**: FastAPI
*   **ASGI 服务器**: Uvicorn
*   **协议库**:
    *   OIDC/JWT: `python-jose`
*   **HTTP 客户端**: `httpx` (异步)
*   **数据存储**:
    *   Redis (Session, Cache)
    *   SQLAlchemy (Configuration, Audit Logs - 支持 PostgreSQL/MySQL)
*   **配置管理**: `pydantic-settings`

## 项目结构

```
dingbridge/
├── app/
│   ├── main.py                  # FastAPI 入口，挂载路由与中间件
│   ├── config.py                # 全局配置（钉钉、OIDC、DB、Redis）
│   ├── dependencies.py          # 依赖注入
│   ├── routers/                 # 路由定义
│   │   ├── oidc.py              # OIDC Provider 端点
│   │   └── dingtalk.py          # 钉钉登录回调
│   ├── services/                # 业务逻辑
│   │   ├── auth_orchestrator.py # 认证编排
│   │   ├── dingtalk_adapter.py  # 钉钉 API 适配
│   │   ├── identity_mapping.py  # 用户属性映射
│   │   ├── session_service.py   # Session 管理
│   │   └── ...
│   ├── models/                  # 数据模型
│   └── security/                # 安全相关（审计、密钥）
├── requirements.txt             # 项目依赖
└── README.md                    # 项目说明
```

## 快速开始

### 前置要求

*   Python 3.12+
*   Redis 服务
*   钉钉开发者账号（创建企业内部应用，获取 AppKey 和 AppSecret）

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置

请在环境变量或 `.env` 文件中配置以下关键参数：

```env
# 钉钉配置
DINGTALK__APP_KEY=your_app_key
DINGTALK__APP_SECRET=your_app_secret
DINGTALK__CALLBACK_URL=http://localhost:8000/dingtalk/callback
DINGTALK__FETCH_USER_DETAILS=true

# OIDC IdP 全局配置（也可由数据库覆盖）
OIDC__ISSUER=http://localhost:8000
OIDC__ID_TOKEN_EXP_MINUTES=60
OIDC__ACCESS_TOKEN_EXP_MINUTES=30
OIDC__REFRESH_TOKEN_EXP_MINUTES=43200

# 默认 OIDC Client（也可由数据库覆盖 / 扩展为多个）
OIDC__CLIENT_ID=coze-client-id
OIDC__CLIENT_SECRET=coze-client-secret
OIDC__REDIRECT_URI=https://coze.example.com/oidc/callback

# Redis
REDIS__HOST=127.0.0.1
REDIS__PORT=6379
REDIS__PASSWORD=
REDIS__DB=1

# 数据库（用于动态配置）
DATABASE__URL=sqlite:///./dingbridge.sqlite3

# 可选：启用管理接口（/admin/*）
SECURITY__ADMIN_API_KEY=change_me

# 生产环境必须注入稳定 RSA 私钥，可用 PEM 内容或文件路径
SECURITY__JWT_PRIVATE_KEY=
SECURITY__JWT_PRIVATE_KEY_PATH=
SECURITY__JWT_PUBLIC_KEY=
SECURITY__JWT_PUBLIC_KEY_PATH=
SECURITY__ALLOW_EPHEMERAL_KEYS=false
```

### 运行服务

```bash
uvicorn app.main:app --reload
```

服务启动后，可访问 Swagger 文档查看接口：`http://127.0.0.1:8000/docs`

## 动态配置（数据库）

服务启动时会自动创建配置相关表，并将 `.env` 中的默认配置作为初始数据写入（如果表为空）。

*   **全局 IdP 配置**: `idp_settings`（OIDC Issuer、Token 过期）
*   **OIDC Clients**: `oidc_clients`（支持多个 ClientID/Secret/RedirectURI 列表）
*   **钉钉应用**: `dingtalk_apps`（可为不同 OIDC Client 绑定不同钉钉 App）

当数据库中的配置被更新后，服务会按缓存 TTL 自动刷新；也可以调用 `POST /admin/reload` 立即刷新。

### 管理接口

设置 `SECURITY__ADMIN_API_KEY` 后会启用 `/admin/*`，通过请求头 `X-Admin-Key` 访问。接口会避免回传敏感字段（如 ClientSecret、AppSecret）。

## 关键 API 端点

### OIDC
*   `GET /.well-known/openid-configuration`: OIDC Discovery 文档
*   `GET /oidc/authorize`: 授权端点
*   `POST /oidc/token`: 令牌端点（支持 `authorization_code` 与 `refresh_token`）
*   `GET /oidc/userinfo`: 用户信息端点
*   `GET /oidc/jwks.json`: 公钥集合
*   `GET /oidc/logout`: 浏览器登出端点（支持 `id_token_hint` / `post_logout_redirect_uri` / `state`）
*   `POST /oidc/logout`: API 登出端点（可撤销 `refresh_token`，支持 `id_token_hint` / `post_logout_redirect_uri` / `state`）

### DingTalk
*   `GET /dingtalk/login`: 发起钉钉登录
*   `GET /dingtalk/callback`: 钉钉回调处理

## 部署建议

*   建议部署在云服务器或 K8s 环境中。
*   使用 Nginx 或 Ingress Controller 进行反向代理，配置 HTTPS。
*   生产环境建议配置负载均衡和多实例以保证高可用。

## 开发计划 (Roadmap)

*   [ ] **todo-arch**: 完善架构文档与接口契约
*   [ ] **todo-dingtalk-adapter**: 增强钉钉适配层，支持更多字段和部门信息
*   [ ] **todo-oidc-provider**: 完善 OIDC 协议支持 (更多 Grant Types)
*   [ ] **todo-identity-mapping**: 实现可配置的属性映射规则
*   [ ] **todo-security**: 密钥管理、CSRF 防护、重放攻击防护
*   [ ] **todo-deploy**: 编写部署脚本和监控告警方案
