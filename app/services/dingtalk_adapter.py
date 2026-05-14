from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
import logging

from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.services.client_registry import DingTalkApp


logger = logging.getLogger("dingbridge.dingtalk")


class DingTalkAPIError(RuntimeError):
    """
    钉钉开放平台调用错误。
    统一异常类型便于上层记录日志和统一处理。
    """


def _presence_summary(data: Dict[str, Any], *fields: str) -> str:
    return " ".join(f"has_{field}={bool(data.get(field))}" for field in fields)


def _request_id_from_headers(resp: httpx.Response) -> str | None:
    return resp.headers.get("x-acs-request-id") or resp.headers.get("x-acs-trace-id")


def _app_debug_summary(app: DingTalkApp) -> dict:
    return {
        "id": app.id,
        "name": app.name,
        "enabled": app.enabled,
        "is_default": app.is_default,
        "app_key": app.app_key,
        "callback_url": str(app.callback_url),
    }


def _debug_dump_value(value: Any) -> Any:
    secret_keys = {
        "access_token",
        "accesstoken",
        "refresh_token",
        "refreshtoken",
        "accessToken",
        "accesstoken",
        "refreshToken",
        "appsecret",
        "app_secret",
        "appSecret",
        "client_secret",
        "clientSecret",
        "clientsecret",
        "secret",
        "token",
        "code",
        "authCode",
        "authcode",
        "state",
        "x-acs-dingtalk-access-token",
        "x_acs_dingtalk_access_token",
        "xacsdingtalkaccesstoken",
    }
    profile_keys = {
        "address",
        "avatar",
        "avatar_url",
        "avatarurl",
        "dept_name_list",
        "dept_names",
        "deptnamelist",
        "deptnames",
        "email",
        "extension",
        "job_number",
        "jobnumber",
        "manager_userid",
        "manageruserid",
        "mobile",
        "name",
        "nick",
        "nickname",
        "org_email",
        "orgemail",
        "phone",
        "phone_number",
        "phonenumber",
        "remark",
        "state_code",
        "statecode",
        "telephone",
        "title",
        "work_place",
        "workplace",
    }
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized = key_text.lower().replace("-", "_")
            compact = normalized.replace("_", "")
            if normalized in secret_keys or compact in secret_keys or normalized in profile_keys or compact in profile_keys:
                out[key_text] = "***REDACTED***"
            else:
                out[key_text] = _debug_dump_value(item)
        return out
    if isinstance(value, list):
        return [_debug_dump_value(item) for item in value]
    if hasattr(value, "to_map"):
        try:
            return _debug_dump_value(value.to_map())
        except Exception:
            return repr(value)
    return value


def build_oauth_login_url(*, state: str, app: DingTalkApp) -> str:
    """
    构造钉钉 OAuth 登录 URL。
    """
    # 登录授权阶段只申请钉钉身份凭证所需范围；通讯录读取权限由应用后台权限控制。
    scope = "openid corpid"

    endpoint = str(settings.dingtalk.auth_base_url).rstrip("/")
    params = {
        "client_id": app.app_key,
        "redirect_uri": str(app.callback_url),
        "response_type": "code",
        "scope": scope,
        "state": state,
    }
    logger.debug(
        "dingtalk_oauth_login_url_build endpoint=%s app=%r params=%r",
        endpoint,
        _app_debug_summary(app),
        params,
    )

    login_url = f"{endpoint}?{urlencode(params)}"
    logger.debug("dingtalk_oauth_login_url_result endpoint=%s has_login_url=%s", endpoint, bool(login_url))
    return login_url


# ---------------------------------------------------------------------------
# 同步辅助函数（运行在 run_in_threadpool 中）
# 每个函数只做一件事，便于单独测试和维护。
# ---------------------------------------------------------------------------


def _exchange_user_access_token(code: str, app: DingTalkApp) -> str:
    """
    通过授权 code 换取用户 AccessToken（UserAccessToken）。
    使用钉钉 REST API，同步执行。
    """
    endpoint = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"
    body = {
        "clientId": app.app_key,
        "clientSecret": app.app_secret,
        "code": code,
        "grantType": "authorization_code",
    }
    try:
        logger.debug(
            "dingtalk_user_token_request endpoint=%s body=%r",
            endpoint,
            body,
        )
        resp = httpx.post(endpoint, json=body, timeout=5.0)
        logger.debug(
            "dingtalk_user_token_response status_code=%s request_id=%s",
            resp.status_code,
            _request_id_from_headers(resp),
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = {"body": (resp.text or "")[:500]}
            logger.warning(
                "dingtalk_user_token_failed status_code=%s code=%s message=%s requestid=%s",
                resp.status_code,
                err.get("code"),
                err.get("message"),
                err.get("requestid") or err.get("request_id"),
                extra={"event": "dingtalk_user_token_failed"},
            )
            logger.debug("dingtalk_user_token_result ok=false body=%r", err)
            resp.raise_for_status()

        data = resp.json()
        logger.debug("dingtalk_user_token_raw body=%r", data)
        token = data.get("accessToken")
        if not token:
            logger.debug("dingtalk_user_token_result ok=false reason=missing_accessToken body=%r", data)
            raise DingTalkAPIError("Failed to get userAccessToken: missing accessToken")
        logger.debug("dingtalk_user_token_result ok=true has_access_token=%s", bool(token))
        return token
    except Exception as e:
        logger.warning(
            "dingtalk_user_token_failed",
            extra={"event": "dingtalk_user_token_failed", "error_type": type(e).__name__},
        )
        logger.debug(
            "dingtalk_user_token_failed error_type=%s error=%r",
            type(e).__name__,
            e,
            exc_info=True,
        )
        if isinstance(e, DingTalkAPIError):
            raise
        raise DingTalkAPIError(f"REST: Failed to get userAccessToken: {e}") from e


def _fetch_user_basic_info_via_rest(user_access_token: str) -> Optional[Dict[str, Any]]:
    """
    通过 REST API 获取用户通讯录个人信息。
    返回原始字段字典；失败时返回 None。
    """
    try:
        endpoint = "https://api.dingtalk.com/v1.0/contact/users/me"
        headers = {"x-acs-dingtalk-access-token": user_access_token}
        logger.debug(
            "dingtalk_user_basic_request endpoint=%s headers=%r",
            endpoint,
            headers,
        )
        resp = httpx.get(
            endpoint,
            headers=headers,
            timeout=5.0,
        )
        logger.debug(
            "dingtalk_user_basic_response status_code=%s request_id=%s",
            resp.status_code,
            _request_id_from_headers(resp),
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = {"body": (resp.text or "")[:500]}
            logger.warning(
                "dingtalk_user_basic_failed status_code=%s code=%s message=%s requestid=%s",
                resp.status_code,
                err.get("code"),
                err.get("message"),
                err.get("requestid") or err.get("request_id"),
                extra={"event": "dingtalk_user_basic_failed"},
            )
            logger.debug(
                "dingtalk_user_basic_result ok=false body=%r",
                err,
            )
            resp.raise_for_status()
        data = resp.json()
        logger.debug("dingtalk_user_basic_raw body=%r", data)
        result = {
            "openId": data.get("openId"),
            "name": data.get("nick"),
            "email": data.get("email"),
            "mobile": data.get("mobile"),
            "avatar": data.get("avatarUrl"),
            "state_code": data.get("stateCode"),
        }
        logger.debug(
            "dingtalk_user_basic_result ok=true %s",
            _presence_summary(result, "openId", "name", "email", "mobile"),
        )
        return result
    except Exception as e:
        logger.warning(
            "dingtalk_user_basic_exception",
            extra={"event": "dingtalk_user_basic_exception", "error_type": type(e).__name__},
        )
        logger.debug(
            "dingtalk_user_basic_exception error_type=%s error=%r",
            type(e).__name__,
            e,
            exc_info=True,
        )
        return None


def _get_user_info_sync(code: str, app: DingTalkApp) -> Dict[str, Any]:
    """
    主流程：通过钉钉 OAuth code 获取完整用户信息。

    流程：
    1. 换取 UserAccessToken
    2. 通过 REST API 获取 openId/邮箱等用户信息
    """
    # Step 1: 换取 UserAccessToken（失败直接抛出，无法继续）
    user_access_token = _exchange_user_access_token(code, app)

    result: Dict[str, Any] = {}
    open_id: Optional[str] = None

    # Step 2: 通过 REST API 获取用户信息
    logger.debug(
        "dingtalk_user_basic_start reason=missing_identity has_openId=%s",
        bool(open_id),
    )
    basic = _fetch_user_basic_info_via_rest(user_access_token)
    if basic:
        open_id = open_id or basic.get("openId")
        if not result:
            result = basic
        else:
            # 只补充缺失字段
            for k, v in basic.items():
                if not result.get(k):
                    result[k] = v

    # 如果两步都失败，无法继续
    if not result:
        logger.debug("dingtalk_user_info_failed reason=empty_result")
        raise DingTalkAPIError("Failed to get any user info from DingTalk")

    # 确保关键主键字段填充
    if open_id and not result.get("openId"):
        result["openId"] = open_id

    logger.debug(
        "dingtalk_user_info_success %s",
        _presence_summary(result, "openId", "name", "email", "mobile"),
    )
    logger.debug("dingtalk_user_info_raw result=%r", _debug_dump_value(result))

    return result


async def fetch_user_info(code: str, app: DingTalkApp) -> Dict[str, Any]:
    """
    获取用户信息（异步封装）。
    """
    return await run_in_threadpool(_get_user_info_sync, code, app)


def _normalize_dingtalk_user(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    将钉钉原始用户信息结构归一化为统一字典。
    """
    # 兼容钉钉 API 返回的驼峰和下划线/混合风格
    user_id = raw.get("userId") or raw.get("openId")

    # 部门信息处理
    dept_ids = raw.get("dept_id_list") or raw.get("deptIds") or []
    if dept_ids and not isinstance(dept_ids, list):
        dept_ids = []

    dept_names = raw.get("dept_name_list") or raw.get("dept_names") or []

    is_admin = bool(raw.get("is_admin") or raw.get("isAdmin") or False)

    email = raw.get("email") or raw.get("orgEmail")

    normalized: Dict[str, Any] = {
        "userId": user_id,
        "name": raw.get("name"),
        "email": email,
        "mobile": raw.get("mobile"),
        "deptIds": dept_ids,
        "dept_names": dept_names,
        "isAdmin": is_admin,
        "raw": raw,
    }

    logger.debug("dingtalk_user_normalized_raw body=%r", _debug_dump_value(normalized))
    return normalized


async def fetch_normalized_user_info(code: str, app: DingTalkApp) -> Dict[str, Any]:
    """
    高层封装：直接返回统一结构的钉钉用户信息。
    """
    raw = await fetch_user_info(code, app)
    return _normalize_dingtalk_user(raw)
