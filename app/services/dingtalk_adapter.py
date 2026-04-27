from typing import Any, Dict
from urllib.parse import urlencode

import logging
import httpx
from starlette.concurrency import run_in_threadpool

from alibabacloud_dingtalk.oauth2_1_0.client import Client as OAuth2Client
from alibabacloud_dingtalk.oauth2_1_0 import models as oauth2_models
from alibabacloud_dingtalk.contact_1_0.client import Client as ContactClient
from alibabacloud_dingtalk.contact_1_0 import models as contact_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

from app.config import settings
from app.services.cache import get_redis
from app.services.client_registry import DingTalkApp


logger = logging.getLogger("dingbridge.dingtalk")


class DingTalkAPIError(RuntimeError):
    """
    钉钉开放平台调用错误。
    统一异常类型便于上层记录日志和统一处理。
    """


def build_oauth_login_url(*, state: str, app: DingTalkApp) -> str:
    """
    构造钉钉 OAuth 登录 URL。
    """
    # 根据配置动态决定 scope
    # 如果开启了获取详细信息，必须在 scope 中包含 Contact.User.Read
    # 否则默认只请求基础身份信息
    scope = "openid corpid"
    if app.fetch_user_details:
        scope = "openid corpid Contact.User.Read"

    query = urlencode(
        {
            "client_id": app.app_key,
            "redirect_uri": str(app.callback_url),
            "response_type": "code",
            "scope": scope,
            "state": state,
        }
    )
    return f"{str(settings.dingtalk.auth_base_url).rstrip('/')}?{query}"


async def fetch_access_token(app: DingTalkApp) -> str:
    """
    获取钉钉 access_token (App AccessToken)。
    优先从 Redis 缓存获取，失效则重新请求并缓存。
    """
    redis = get_redis()
    cache_key = f"dingbridge:dingtalk:{app.app_key}:access_token"
    
    token = await redis.get(cache_key)
    if token:
        return token

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            str(settings.dingtalk.token_base_url),
            params={
                "appkey": app.app_key,
                "appsecret": app.app_secret,
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            logger.warning(
                "dingtalk_app_token_failed",
                extra={
                    "event": "dingtalk_app_token_failed",
                    "errcode": data.get("errcode"),
                    "errmsg": data.get("errmsg"),
                    "request_id": data.get("request_id"),
                },
            )
            raise DingTalkAPIError(
                f"Failed to get dingtalk token: errcode={data.get('errcode')} errmsg={data.get('errmsg')} request_id={data.get('request_id')}"
            )
        
        token = data["access_token"]
        # 缓存有效期：默认 7200 秒，保守设置减去 200 秒
        expires_in = data.get("expires_in", 7200)
        ttl = max(expires_in - 200, 60)
        
        await redis.set(cache_key, token, ex=ttl)
        return token


def _fetch_app_access_token_sync(app: DingTalkApp) -> str:
    with httpx.Client() as client:
        resp = client.get(
            str(settings.dingtalk.token_base_url),
            params={
                "appkey": app.app_key,
                "appsecret": app.app_secret,
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            logger.warning(
                "dingtalk_app_token_failed",
                extra={
                    "event": "dingtalk_app_token_failed",
                    "errcode": data.get("errcode"),
                    "errmsg": data.get("errmsg"),
                    "request_id": data.get("request_id"),
                },
            )
            raise DingTalkAPIError(
                f"Failed to get dingtalk token: errcode={data.get('errcode')} errmsg={data.get('errmsg')} request_id={data.get('request_id')}"
            )
        return data["access_token"]


def _get_userid_by_unionid_sync(app_access_token: str, union_id: str) -> str | None:
    with httpx.Client() as client:
        resp = client.post(
            "https://oapi.dingtalk.com/topapi/user/getbyunionid",
            params={"access_token": app_access_token},
            json={"unionid": union_id},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            logger.warning(
                "dingtalk_get_userid_failed",
                extra={
                    "event": "dingtalk_get_userid_failed",
                    "errcode": data.get("errcode"),
                    "errmsg": data.get("errmsg"),
                    "request_id": data.get("request_id"),
                },
            )
            return None
        result = data.get("result") or {}
        return result.get("userid")


def _get_user_detail_by_userid_sync(app_access_token: str, user_id: str) -> Dict[str, Any]:
    with httpx.Client() as client:
        resp = client.post(
            "https://oapi.dingtalk.com/topapi/v2/user/get",
            params={"access_token": app_access_token},
            json={"userid": user_id},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            logger.warning(
                "dingtalk_user_detail_oapi_failed",
                extra={
                    "event": "dingtalk_user_detail_oapi_failed",
                    "errcode": data.get("errcode"),
                    "errmsg": data.get("errmsg"),
                    "request_id": data.get("request_id"),
                },
            )
            return {}
        return data.get("result") or {}


def _get_user_info_sync(code: str, app: DingTalkApp) -> Dict[str, Any]:
    """
    使用官方 SDK 同步获取用户信息（运行在线程池中）。
    """
    config = open_api_models.Config(
        protocol='https',
        region_id='central'
    )
    
    # 1. 换取 UserAccessToken
    oauth_client = OAuth2Client(config)
    token_request = oauth2_models.GetUserTokenRequest(
        client_id=app.app_key,
        client_secret=app.app_secret,
        code=code,
        grant_type='authorization_code'
    )
    
    try:
        token_response = oauth_client.get_user_token(token_request)
        user_access_token = token_response.body.access_token
    except Exception as e:
        logger.warning(
            "dingtalk_user_token_failed",
            extra={"event": "dingtalk_user_token_failed", "error_type": type(e).__name__},
        )
        raise DingTalkAPIError(f"SDK: Failed to get userAccessToken: {str(e)}")

    # 2. 获取用户信息
    contact_client = ContactClient(config)
    headers = contact_models.GetUserHeaders(
        x_acs_dingtalk_access_token=user_access_token
    )
    
    result = {}
    union_id = None
    open_id = None
    try:
        if app.fetch_user_details:
            user_response = contact_client.get_user_with_options(
                'me', headers, util_models.RuntimeOptions()
            )
            body = user_response.body
            union_id = body.union_id
            open_id = body.open_id
            result = {
                "userid": body.open_id, # SDK 返回的是驼峰
                "openId": body.open_id,
                "unionid": body.union_id,
                "name": body.nick,
                "email": body.email,
                "mobile": body.mobile,
                "avatar": body.avatar_url,
                "state_code": body.state_code
            }
    except Exception as e:
        logger.warning(
            "dingtalk_user_detail_failed",
            extra={
                "event": "dingtalk_user_detail_failed",
                "fetch_user_details": app.fetch_user_details,
                "error_type": type(e).__name__,
            },
        )
    
    if not union_id or not open_id:
        import httpx as sync_httpx
        try:
            resp = sync_httpx.get(
                "https://api.dingtalk.com/v1.0/contact/users/me",
                headers={"x-acs-dingtalk-access-token": user_access_token},
                timeout=5.0
            )
            if resp.status_code >= 400:
                try:
                    err = resp.json()
                except Exception:
                    err = {"body": (resp.text or "")[:500]}
                logger.warning(
                    "dingtalk_user_basic_failed",
                    extra={
                        "event": "dingtalk_user_basic_failed",
                        "status_code": resp.status_code,
                        "code": err.get("code"),
                        "message": err.get("message"),
                        "requestid": err.get("requestid") or err.get("request_id"),
                    },
                )
            resp.raise_for_status()
            data = resp.json()
            open_id = open_id or data.get("openId")
            union_id = union_id or data.get("unionId")
            if not result:
                result = {
                    "userid": data.get("openId"),
                    "openId": data.get("openId"),
                    "unionid": data.get("unionId"),
                    "name": data.get("nick"),
                    "avatar": data.get("avatarUrl")
                }
        except Exception as inner_e:
            logger.warning(
                "dingtalk_user_basic_exception",
                extra={"event": "dingtalk_user_basic_exception", "error_type": type(inner_e).__name__},
            )
            if not result:
                raise DingTalkAPIError(f"SDK: Failed to get basic user info: {str(inner_e)}")

    if union_id:
        try:
            app_access_token = _fetch_app_access_token_sync(app)
            user_id = _get_userid_by_unionid_sync(app_access_token, union_id)
            if user_id:
                detail = _get_user_detail_by_userid_sync(app_access_token, user_id)
                if detail:
                    result.update({k: v for k, v in detail.items() if v is not None})
                if not result.get("userid"):
                    result["userid"] = user_id
                if not result.get("unionid"):
                    result["unionid"] = union_id
                if open_id and not result.get("openId"):
                    result["openId"] = open_id
        except Exception as e:
            logger.warning(
                "dingtalk_user_detail_oapi_exception",
                extra={"event": "dingtalk_user_detail_oapi_exception", "error_type": type(e).__name__},
            )

    if not result:
        raise DingTalkAPIError("SDK: Failed to get user info")

    return result


async def fetch_user_info(code: str, app: DingTalkApp) -> Dict[str, Any]:
    """
    使用 SDK 获取用户信息（异步封装）。
    """
    return await run_in_threadpool(_get_user_info_sync, code, app)


def _normalize_dingtalk_user(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    将钉钉原始用户信息结构归一化为统一字典。
    """
    # 兼容 SDK 返回的驼峰和 API 返回的下划线/混合风格
    user_id = raw.get("userid") or raw.get("userId") or raw.get("openId")
    union_id = raw.get("unionid") or raw.get("unionId")

    # 部门信息处理（SDK 返回的可能是列表对象，需转换）
    dept_ids = raw.get("dept_id_list") or raw.get("deptIds") or []
    if dept_ids and not isinstance(dept_ids, list):
        # 简单防范
        dept_ids = []
        
    dept_names = raw.get("dept_name_list") or raw.get("dept_names") or []

    is_admin = bool(raw.get("is_admin") or raw.get("isAdmin") or False)
    
    # 邮箱处理：优先使用 org_email (企业邮箱)，其次使用 email (个人邮箱)
    email = raw.get("org_email") or raw.get("email") or raw.get("orgEmail")

    normalized: Dict[str, Any] = {
        "userId": user_id,
        "unionId": union_id,
        "name": raw.get("name"),
        "email": email,
        "mobile": raw.get("mobile"),
        "deptIds": dept_ids,
        "dept_names": dept_names,
        "isAdmin": is_admin,
        "raw": raw,
    }

    # 兼容现有 identity_mapping 中的字段使用习惯
    if user_id is not None:
        normalized["userid"] = user_id
    if union_id is not None:
        normalized["unionid"] = union_id

    return normalized


async def fetch_normalized_user_info(code: str, app: DingTalkApp) -> Dict[str, Any]:
    """
    高层封装：直接返回统一结构的钉钉用户信息。
    """
    raw = await fetch_user_info(code, app)
    return _normalize_dingtalk_user(raw)
