from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class DingTalkSettings(BaseSettings):
    app_key: str = ""
    app_secret: str = ""
    # 钉钉 OAuth2 授权地址 (固定)
    auth_base_url: AnyHttpUrl = "https://login.dingtalk.com/oauth2/auth"
    # 钉钉 AccessToken 获取接口 (固定)
    token_base_url: AnyHttpUrl = "https://oapi.dingtalk.com/gettoken"
    # 钉钉用户信息获取接口 (固定)
    user_info_url: AnyHttpUrl = "https://oapi.dingtalk.com/topapi/v2/user/get"
    # 钉钉回调地址：需与钉钉开发者后台配置的一致
    # 格式：http(s)://{你的 dingbridge 域名}/dingtalk/callback
    callback_url: AnyHttpUrl = "https://sso-dingbridge.chinaclawbook.com/dingtalk/callback"
    
    # 是否获取用户详细信息（如手机号、邮箱、部门等）
    # 注意：如果开启此项，必须在钉钉开发者后台开通 "通讯录个人信息读权限" (Contact.User.Read)
    fetch_user_details: bool = True


class OIDCSettings(BaseSettings):
    # OIDC Issuer: 标识当前 OIDC Provider 的身份
    # 格式：http(s)://{你的 dingbridge 域名}
    issuer: AnyHttpUrl = "https://sso-dingbridge.chinaclawbook.com"
    # Coze 分配的 Client ID
    client_id: str = "coze-client-id"
    # Coze 分配的 Client Secret
    client_secret: str = "coze-client-secret"
    # Coze 的 OIDC 回调地址
    # 格式：https://www.coze.cn/api/passport/oidc/callback
    redirect_uri: AnyHttpUrl = "https://coze.example.com/oidc/callback"
    id_token_exp_minutes: int = 60
    access_token_exp_minutes: int = 30
    refresh_token_exp_minutes: int = 60 * 24 * 30


class RedisSettings(BaseSettings):
    host: str = "10.101.232.216"
    port: int = 6379
    password: str = ""
    db: int = 1


class DatabaseSettings(BaseSettings):
    url: str = "sqlite:///./dingbridge.sqlite3"


class SecuritySettings(BaseSettings):
    # 注意：
    # - 默认不内置任何真实密钥，便于本地开发时使用进程内临时密钥对
    # - 生产环境务必通过环境变量或专用密钥管理系统注入 PEM
    jwt_private_key: str = ""
    jwt_public_key: str = ""
    # 支持从文件加载密钥（Docker 容器场景常用）
    jwt_private_key_path: str = ""
    jwt_public_key_path: str = ""
    
    jwt_algorithm: str = "RS256"
    allow_ephemeral_keys: bool = False
    cookie_name: str = "dingbridge_sso"
    cookie_domain: str | None = None
    cookie_secure: bool = True
    cookie_samesite: str = "lax"
    # 本地 SSO Session 的默认有效期（分钟），配合 session_service 使用
    session_ttl_minutes: int = 60
    admin_api_key: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )
    dingtalk: DingTalkSettings = DingTalkSettings()
    oidc: OIDCSettings = OIDCSettings()
    redis: RedisSettings = RedisSettings()
    database: DatabaseSettings = DatabaseSettings()
    security: SecuritySettings = SecuritySettings()


settings = Settings()
