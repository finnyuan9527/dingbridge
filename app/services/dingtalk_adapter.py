from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
import logging

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


# ---------------------------------------------------------------------------
# 同步辅助函数（运行在 run_in_threadpool 中）
# 每个函数只做一件事，便于单独测试和维护。
# ---------------------------------------------------------------------------

def _fetch_app_access_token_sync(app: DingTalkApp) -> str:
    """获取钉钉企业应用 AccessToken（同步）。"""
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


def _exchange_user_access_token(code: str, app: DingTalkApp) -> str:
    """
    通过授权 code 换取用户 AccessToken（UserAccessToken）。
    使用官方 SDK，同步执行。
    """
    config = open_api_models.Config(protocol="https", region_id="central")
    oauth_client = OAuth2Client(config)
    token_request = oauth2_models.GetUserTokenRequest(
        client_id=app.app_key,
        client_secret=app.app_secret,
        code=code,
        grant_type="authorization_code",
    )
    try:
        token_response = oauth_client.get_user_token(token_request)
        return token_response.body.access_token
    except Exception as e:
        logger.warning(
            "dingtalk_user_token_failed",
            extra={"event": "dingtalk_user_token_failed", "error_type": type(e).__name__},
        )
        raise DingTalkAPIError(f"SDK: Failed to get userAccessToken: {e}") from e


def _fetch_user_detail_via_sdk(user_access_token: str, app: DingTalkApp) -> Optional[Dict[str, Any]]:
    """
    通过 SDK 获取用户详细信息（需 Contact.User.Read 权限）。
    返回归一化前的原始字段字典；失败时返回 None（由调用方决定是否 fallback）。
    """
    config = open_api_models.Config(protocol="https", region_id="central")
    contact_client = ContactClient(config)
    headers = contact_models.GetUserHeaders(x_acs_dingtalk_access_token=user_access_token)
    try:
        user_response = contact_client.get_user_with_options("me", headers, util_models.RuntimeOptions())
        body = user_response.body
        return {
            "userid": body.open_id,
            "openId": body.open_id,
            "unionid": body.union_id,
            "name": body.nick,
            "email": body.email,
            "mobile": body.mobile,
            "avatar": body.avatar_url,
            "state_code": body.state_code,
        }
    except Exception as e:
        logger.warning(
            "dingtalk_user_detail_sdk_failed",
            extra={
                "event": "dingtalk_user_detail_sdk_failed",
                "error_type": type(e).__name__,
            },
        )
        return None


def _fetch_user_basic_info_via_rest(user_access_token: str) -> Optional[Dict[str, Any]]:
    """
    通过 REST API 获取用户基础信息（openId / unionId / nick）。
    作为 SDK 详情接口失败时的 fallback。
    返回原始字段字典；失败时返回 None。
    """
    try:
        resp = httpx.get(
            "https://api.dingtalk.com/v1.0/contact/users/me",
            headers={"x-acs-dingtalk-access-token": user_access_token},
            timeout=5.0,
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
        return {
            "userid": data.get("openId"),
            "openId": data.get("openId"),
            "unionid": data.get("unionId"),
            "name": data.get("nick"),
            "avatar": data.get("avatarUrl"),
        }
    except Exception as e:
        logger.warning(
            "dingtalk_user_basic_exception",
            extra={"event": "dingtalk_user_basic_exception", "error_type": type(e).__name__},
        )
        return None


def _get_userid_by_unionid_sync(app_access_token: str, union_id: str) -> Optional[str]:
    """通过 unionId 查询企业内 userId（同步）。"""
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
    """通过企业内 userId 查询用户详情（部门、手机号、邮箱等）（同步）。"""
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


def _enrich_with_oapi(result: Dict[str, Any], union_id: str, app: DingTalkApp) -> Dict[str, Any]:
    """
    尝试通过 OAPI（企业通讯录接口）补充用户详情（部门、手机、邮箱等）。
    失败时静默返回原始 result，不影响主流程。
    """
    try:
        app_access_token = _fetch_app_access_token_sync(app)
        user_id = _get_userid_by_unionid_sync(app_access_token, union_id)
        if user_id:
            detail = _get_user_detail_by_userid_sync(app_access_token, user_id)
            if detail:
                # 只用非空值补充，不覆盖已有字段
                result.update({k: v for k, v in detail.items() if v is not None})
            # 确保主键字段存在
            if not result.get("userid"):
                result["userid"] = user_id
            if not result.get("unionid"):
                result["unionid"] = union_id
    except Exception as e:
        logger.warning(
            "dingtalk_oapi_enrich_failed",
            extra={"event": "dingtalk_oapi_enrich_failed", "error_type": type(e).__name__},
        )
    return result


def _get_user_info_sync(code: str, app: DingTalkApp) -> Dict[str, Any]:
    """
    主流程：通过钉钉 OAuth code 获取完整用户信息。

    流程：
    1. 换取 UserAccessToken
    2. 若 fetch_user_details=True，尝试 SDK 获取详情
    3. 无论 SDK 是否成功，通过 REST API 获取 openId/unionId（确保主键存在）
    4. 若有 unionId，通过 OAPI 补充企业详情（部门、手机等）
    """
    # Step 1: 换取 UserAccessToken（失败直接抛出，无法继续）
    user_access_token = _exchange_user_access_token(code, app)

    result: Dict[str, Any] = {}
    open_id: Optional[str] = None
    union_id: Optional[str] = None

    # Step 2: 优先尝试 SDK 获取详细信息
    if app.fetch_user_details:
        sdk_result = _fetch_user_detail_via_sdk(user_access_token, app)
        if sdk_result:
            result = sdk_result
            open_id = sdk_result.get("openId")
            union_id = sdk_result.get("unionid")

    # Step 3: 若尚未获得 openId/unionId，通过 REST API 获取基础信息
    if not open_id or not union_id:
        basic = _fetch_user_basic_info_via_rest(user_access_token)
        if basic:
            open_id = open_id or basic.get("openId")
            union_id = union_id or basic.get("unionid")
            if not result:
                result = basic
            else:
                # 只补充缺失字段
                for k, v in basic.items():
                    if not result.get(k):
                        result[k] = v

    # 如果两步都失败，无法继续
    if not result:
        raise DingTalkAPIError("Failed to get any user info from DingTalk")

    # 确保关键主键字段填充
    if open_id and not result.get("openId"):
        result["openId"] = open_id
    if union_id and not result.get("unionid"):
        result["unionid"] = union_id

    # Step 4: 通过 OAPI 补充企业详情（部门等），失败不影响主流程
    if union_id:
        result = _enrich_with_oapi(result, union_id, app)

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
