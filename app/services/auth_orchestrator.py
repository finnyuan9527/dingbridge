import logging
from typing import Optional
from urllib.parse import urlencode

from fastapi import Request

from app.config import settings
from app.models.user import User
from app.security import audit
from app.services import client_registry, dingtalk_adapter, identity_mapping, session_service


logger = logging.getLogger("dingbridge.dingtalk")


class RequireLogin(Exception):
    def __init__(self, redirect_to: str):
        self.redirect_to = redirect_to


def _app_debug_summary(app: client_registry.DingTalkApp) -> dict:
    return {
        "id": app.id,
        "name": app.name,
        "enabled": app.enabled,
        "is_default": app.is_default,
        "app_key": app.app_key,
        "callback_url": str(app.callback_url),
    }


def _dingtalk_data_summary(data: dict) -> dict:
    return {
        "has_userId": bool(data.get("userId") or data.get("userid")),
        "has_name": bool(data.get("name")),
        "has_email": bool(data.get("email")),
        "has_mobile": bool(data.get("mobile")),
        "dept_count": len(data.get("deptIds") or []),
        "group_count": len(data.get("dept_names") or []),
    }


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
        await audit.log_login_success_async(
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
    logger.debug(
        "dingtalk_callback_orchestrator_start client_id=%s dingtalk_app_id=%s has_code=%s",
        client_id,
        dingtalk_app_id,
        bool(code),
    )
    app = None
    if dingtalk_app_id is not None:
        app = client_registry.ClientRegistry.get_dingtalk_app(dingtalk_app_id)
    if not app:
        app = client_registry.ClientRegistry.get_dingtalk_app_for_oidc_client(client_id)
    if not app:
        logger.debug(
            "dingtalk_callback_orchestrator_missing_app client_id=%s dingtalk_app_id=%s",
            client_id,
            dingtalk_app_id,
        )
        raise RuntimeError("missing_dingtalk_app_config")
    logger.debug(
        "dingtalk_callback_orchestrator_app_selected client_id=%s dingtalk_app_id=%s app=%r",
        client_id,
        dingtalk_app_id,
        _app_debug_summary(app),
    )

    try:
        logger.debug(
            "dingtalk_callback_orchestrator_userinfo_start client_id=%s app_key=%s",
            client_id,
            app.app_key,
        )
        dingtalk_data = await dingtalk_adapter.fetch_normalized_user_info(code, app)
    except Exception as e:
        logger.debug(
            "dingtalk_callback_orchestrator_userinfo_failed client_id=%s app_key=%s error_type=%s error=%r",
            client_id,
            app.app_key,
            type(e).__name__,
            e,
            exc_info=True,
        )
        raise
    logger.debug(
        "dingtalk_callback_orchestrator_userinfo_success client_id=%s app_key=%s summary=%r",
        client_id,
        app.app_key,
        _dingtalk_data_summary(dingtalk_data),
    )

    try:
        user = identity_mapping.map_dingtalk_to_user(dingtalk_data)
    except Exception as e:
        logger.debug(
            "dingtalk_callback_orchestrator_mapping_failed client_id=%s app_key=%s error_type=%s error=%r data_summary=%r",
            client_id,
            app.app_key,
            type(e).__name__,
            e,
            _dingtalk_data_summary(dingtalk_data),
            exc_info=True,
        )
        raise
    logger.debug(
        "dingtalk_callback_orchestrator_mapping_success client_id=%s user_subject=%s has_email=%s group_count=%s",
        client_id,
        user.subject,
        bool(user.email),
        len(user.groups),
    )
    return user
