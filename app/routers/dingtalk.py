import json
import logging
import secrets
from datetime import timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.services import auth_orchestrator, client_registry, dingtalk_adapter, session_service
from app.services.cache import get_redis
from app.security import audit

router = APIRouter(prefix="/dingtalk", tags=["dingtalk"])
logger = logging.getLogger("dingbridge.dingtalk")


def _is_safe_redirect_target(redirect: str, issuer: str) -> bool:
    """
    仅允许：
    - 以 / 开头的相对路径
    - 或与 issuer 同 host 的 http(s) 绝对地址
    """
    target = urlparse(redirect)
    issuer_host = urlparse(issuer).netloc

    if target.scheme:
        if target.scheme not in ("http", "https"):
            return False
        return bool(target.netloc) and target.netloc == issuer_host

    if target.netloc:
        return False
    return redirect.startswith("/")


@router.get("/login")
async def dingtalk_login(
    redirect: str, client_id: str | None = None, dingtalk_app_id: int | None = None
) -> RedirectResponse:
    """
    构造钉钉登录 URL 并重定向。
    State 参数携带 redirect 目标，以便回调时跳回。
    """
    # 基础防护：仅允许回跳到与 issuer 相同的站点或相对路径，避免开放重定向。
    issuer = str(client_registry.ClientRegistry.get_idp_settings().oidc_issuer)
    if not _is_safe_redirect_target(redirect, issuer):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_redirect_target")

    state = secrets.token_urlsafe(32)
    redis = get_redis()
    await redis.set(
        f"dingbridge:dingtalk:state:{state}",
        json.dumps({"redirect": redirect, "client_id": client_id, "dingtalk_app_id": dingtalk_app_id}),
        ex=timedelta(minutes=10),
    )

    app = None
    if dingtalk_app_id is not None:
        app = client_registry.ClientRegistry.get_dingtalk_app(dingtalk_app_id)
    if not app:
        app = client_registry.ClientRegistry.get_dingtalk_app_for_oidc_client(client_id)
    if not app:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="missing_dingtalk_app_config")
    login_url = dingtalk_adapter.build_oauth_login_url(state=state, app=app)
    return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
async def dingtalk_callback(request: Request, code: str, state: str):
    """
    处理钉钉回调：
    1. 用 code 换取用户信息
    2. 创建本地 Session
    3. 重定向回 state 指定的地址
    """
    redis = get_redis()
    key = f"dingbridge:dingtalk:state:{state}"
    raw_state = await redis.get(key)
    if not raw_state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_state")
    await redis.delete(key)

    try:
        state_data = json.loads(raw_state)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_state")

    redirect_url = str(state_data.get("redirect") or "")
    client_id = state_data.get("client_id")
    dingtalk_app_id = state_data.get("dingtalk_app_id")

    try:
        user = await auth_orchestrator.handle_dingtalk_callback(
            code, client_id=client_id, dingtalk_app_id=dingtalk_app_id
        )
    except Exception as e:
        logger.debug(
            "dingtalk_callback_failed client_id=%s dingtalk_app_id=%s reason=%s error=%r",
            client_id,
            dingtalk_app_id,
            type(e).__name__,
            e,
            exc_info=True,
        )
        ip = request.client.host if request.client else None
        await audit.log_login_failure_async(
            reason=type(e).__name__,
            source="dingtalk_callback",
            client_id=client_id,
            ip=ip,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dingtalk_login_failed")

    session_id = secrets.token_urlsafe(32)
    await session_service.create_session(session_id, user)
    
    issuer = str(client_registry.ClientRegistry.get_idp_settings().oidc_issuer)
    if not _is_safe_redirect_target(redirect_url, issuer):
        redirect_url = "/"

    resp = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    session_service.set_session_cookie(resp, session_id)
    return resp
