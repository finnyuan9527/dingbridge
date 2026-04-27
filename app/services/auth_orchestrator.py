import secrets
from typing import Optional
from urllib.parse import urlencode

from fastapi import Request

from app.config import settings
from app.models.user import User
from app.security import audit
from app.services import client_registry, dingtalk_adapter, identity_mapping, session_service


class RequireLogin(Exception):
    def __init__(self, redirect_to: str):
        self.redirect_to = redirect_to


async def ensure_user_session_via_dingtalk(
    request: Request, *, client_id: Optional[str] = None, dingtalk_app_id: Optional[int] = None
) -> User:
    """
    如果已有本地 SSO 会话则直接返回用户，否则抛出 RequireLogin 异常。
    """
    cookie_name = settings.security.cookie_name
    session_id = request.cookies.get(cookie_name)
    user = await session_service.get_user_by_session(session_id)
    if user:
        ip = request.client.host if request.client else None
        audit.log_login_success(
            user=user,
            source="session",
            client_id=None,
            ip=ip,
        )
        return user

    # 无会话，需要跳转到 /dingtalk/login
    current_url = str(request.url)
    params = {"redirect": current_url}
    if client_id:
        params["client_id"] = client_id
    if dingtalk_app_id is not None:
        params["dingtalk_app_id"] = str(dingtalk_app_id)
    login_url = f"/dingtalk/login?{urlencode(params)}"
    
    raise RequireLogin(redirect_to=login_url)


async def handle_dingtalk_callback(
    code: str, *, client_id: Optional[str] = None, dingtalk_app_id: Optional[int] = None
) -> User:
    """
    在真实钉钉联调时使用：通过钉钉回调的 code 换取真实用户。
    """
    app = None
    if dingtalk_app_id is not None:
        app = client_registry.ClientRegistry.get_dingtalk_app(dingtalk_app_id)
    if not app:
        app = client_registry.ClientRegistry.get_dingtalk_app_for_oidc_client(client_id)
    if not app:
        raise RuntimeError("missing_dingtalk_app_config")
    dingtalk_data = await dingtalk_adapter.fetch_normalized_user_info(code, app)
    return identity_mapping.map_dingtalk_to_user(dingtalk_data)
