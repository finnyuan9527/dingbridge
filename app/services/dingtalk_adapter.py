from typing import Any, Dict, Optional
from urllib.parse import quote, urlencode

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
    endpoint = str(settings.dingtalk.auth_base_url).rstrip("/")
    params = {
        "client_id": app.app_key,
        "redirect_uri": str(app.callback_url),
        "response_type": "code",
        "scope": "openid corpid",
        "state": state,
        "prompt":"consent"
    }
    logger.debug(
        "dingtalk_oauth_login_url_build endpoint=%s app=%r params=%r",
        endpoint,
        _app_debug_summary(app),
        params,
    )

    login_url = f"{endpoint}?{urlencode(params, quote_via=quote)}"
    logger.debug("dingtalk_oauth_login_url_result login_url=%s has_login_url=%s", login_url, bool(login_url))
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


def _exchange_app_access_token(app: DingTalkApp) -> str:
    """
    获取企业内部应用 AccessToken，用于服务端通讯录接口。
    """
    endpoint = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
    body = {
        "appKey": app.app_key,
        "appSecret": app.app_secret,
    }
    try:
        logger.debug(
            "dingtalk_app_token_request endpoint=%s body=%r",
            endpoint,
            body,
        )
        resp = httpx.post(endpoint, json=body, timeout=5.0)
        logger.debug(
            "dingtalk_app_token_response status_code=%s request_id=%s",
            resp.status_code,
            _request_id_from_headers(resp),
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = {"body": (resp.text or "")[:500]}
            logger.warning(
                "dingtalk_app_token_failed status_code=%s code=%s message=%s requestid=%s",
                resp.status_code,
                err.get("code"),
                err.get("message"),
                err.get("requestid") or err.get("request_id"),
                extra={"event": "dingtalk_app_token_failed"},
            )
            logger.debug("dingtalk_app_token_result ok=false body=%r", err)
            resp.raise_for_status()

        data = resp.json()
        logger.debug("dingtalk_app_token_raw body=%r", data)
        token = data.get("accessToken")
        if not token:
            logger.debug("dingtalk_app_token_result ok=false reason=missing_accessToken body=%r", data)
            raise DingTalkAPIError("Failed to get app accessToken: missing accessToken")
        logger.debug("dingtalk_app_token_result ok=true has_access_token=%s", bool(token))
        return token
    except Exception as e:
        logger.warning(
            "dingtalk_app_token_failed",
            extra={"event": "dingtalk_app_token_failed", "error_type": type(e).__name__},
        )
        logger.debug(
            "dingtalk_app_token_failed error_type=%s error=%r",
            type(e).__name__,
            e,
            exc_info=True,
        )
        if isinstance(e, DingTalkAPIError):
            raise
        raise DingTalkAPIError(f"REST: Failed to get app accessToken: {e}") from e


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
            "unionId": data.get("unionId") or data.get("unionid"),
            "employeeUserId": data.get("userid") or data.get("userId"),
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


def _resolve_userid_by_unionid_via_rest(app_access_token: str, union_id: str) -> Optional[str]:
    """
    通过 unionId 解析企业通讯录 userid。
    这里使用的是应用 accessToken，不是用户 userAccessToken。
    """
    try:
        endpoint = "https://oapi.dingtalk.com/topapi/user/getbyunionid"
        params = {"access_token": app_access_token}
        body = {"unionid": union_id}
        logger.debug(
            "dingtalk_userid_by_unionid_request endpoint=%s params=%r body=%r",
            endpoint,
            params,
            body,
        )
        resp = httpx.post(endpoint, params=params, json=body, timeout=5.0)
        logger.debug(
            "dingtalk_userid_by_unionid_response status_code=%s request_id=%s",
            resp.status_code,
            _request_id_from_headers(resp),
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = {"body": (resp.text or "")[:500]}
            logger.warning(
                "dingtalk_userid_by_unionid_failed status_code=%s code=%s message=%s requestid=%s",
                resp.status_code,
                err.get("errcode") or err.get("code"),
                err.get("errmsg") or err.get("message"),
                err.get("requestid") or err.get("request_id"),
                extra={"event": "dingtalk_userid_by_unionid_failed"},
            )
            logger.debug("dingtalk_userid_by_unionid_result ok=false body=%r", err)
            resp.raise_for_status()

        data = resp.json()
        logger.debug("dingtalk_userid_by_unionid_raw body=%r", data)
        errcode = data.get("errcode")
        if errcode not in (None, 0, "0"):
            logger.warning(
                "dingtalk_userid_by_unionid_failed status_code=%s code=%s message=%s requestid=%s",
                resp.status_code,
                data.get("errcode"),
                data.get("errmsg"),
                data.get("requestid") or data.get("request_id"),
                extra={"event": "dingtalk_userid_by_unionid_failed"},
            )
            logger.debug("dingtalk_userid_by_unionid_result ok=false body=%r", data)
            return None

        result = data.get("result") or {}
        if not isinstance(result, dict):
            logger.debug("dingtalk_userid_by_unionid_result ok=false reason=invalid_result body=%r", data)
            return None

        user_id = result.get("userid") or result.get("userId")
        logger.debug("dingtalk_userid_by_unionid_result ok=true has_userid=%s", bool(user_id))
        return user_id
    except Exception as e:
        logger.warning(
            "dingtalk_userid_by_unionid_exception",
            extra={"event": "dingtalk_userid_by_unionid_exception", "error_type": type(e).__name__},
        )
        logger.debug(
            "dingtalk_userid_by_unionid_exception error_type=%s error=%r",
            type(e).__name__,
            e,
            exc_info=True,
        )
        return None


def _fetch_org_user_detail_via_rest(app_access_token: str, user_id: str) -> Optional[Dict[str, Any]]:
    """
    通过企业内部应用通讯录接口查询用户详情。
    这里使用的是应用 accessToken，不是用户 userAccessToken。
    """
    try:
        endpoint = "https://oapi.dingtalk.com/topapi/v2/user/get"
        params = {"access_token": app_access_token}
        body = {"userid": user_id, "language": "zh_CN"}
        logger.debug(
            "dingtalk_org_user_detail_request endpoint=%s params=%r body=%r",
            endpoint,
            params,
            body,
        )
        resp = httpx.post(endpoint, params=params, json=body, timeout=5.0)
        logger.debug(
            "dingtalk_org_user_detail_response status_code=%s request_id=%s",
            resp.status_code,
            _request_id_from_headers(resp),
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = {"body": (resp.text or "")[:500]}
            logger.warning(
                "dingtalk_org_user_detail_failed status_code=%s code=%s message=%s requestid=%s",
                resp.status_code,
                err.get("errcode") or err.get("code"),
                err.get("errmsg") or err.get("message"),
                err.get("requestid") or err.get("request_id"),
                extra={"event": "dingtalk_org_user_detail_failed"},
            )
            logger.debug("dingtalk_org_user_detail_result ok=false body=%r", err)
            resp.raise_for_status()

        data = resp.json()
        logger.debug("dingtalk_org_user_detail_raw body=%r", data)
        errcode = data.get("errcode")
        if errcode not in (None, 0, "0"):
            logger.warning(
                "dingtalk_org_user_detail_failed status_code=%s code=%s message=%s requestid=%s",
                resp.status_code,
                data.get("errcode"),
                data.get("errmsg"),
                data.get("requestid") or data.get("request_id"),
                extra={"event": "dingtalk_org_user_detail_failed"},
            )
            logger.debug("dingtalk_org_user_detail_result ok=false body=%r", data)
            return None

        detail = data.get("result") or {}
        if not isinstance(detail, dict):
            logger.debug("dingtalk_org_user_detail_result ok=false reason=invalid_result body=%r", data)
            return None

        email = detail.get("email") or detail.get("org_email") or detail.get("orgEmail")
        result = {
            "employeeUserId": detail.get("userid") or detail.get("userId") or user_id,
            "name": detail.get("name"),
            "email": email,
            "mobile": detail.get("mobile"),
            "avatar": detail.get("avatar"),
            "dept_id_list": detail.get("dept_id_list"),
            "dept_order_list": detail.get("dept_order_list"),
            "title": detail.get("title"),
            "job_number": detail.get("job_number"),
        }
        logger.debug(
            "dingtalk_org_user_detail_result ok=true %s",
            _presence_summary(result, "employeeUserId", "name", "email", "mobile"),
        )
        return result
    except Exception as e:
        logger.warning(
            "dingtalk_org_user_detail_exception",
            extra={"event": "dingtalk_org_user_detail_exception", "error_type": type(e).__name__},
        )
        logger.debug(
            "dingtalk_org_user_detail_exception error_type=%s error=%r",
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
    2. 通过 REST API 获取 openId 等登录身份信息
    3. 使用企业内部应用 AccessToken 查询企业通讯录详情，优先使用通讯录邮箱
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

    app_access_token: Optional[str] = None
    user_id_for_detail = result.get("employeeUserId")
    union_id = result.get("unionId") or result.get("unionid")
    if not user_id_for_detail and union_id:
        logger.debug(
            "dingtalk_userid_by_unionid_start has_unionId=%s has_openId=%s",
            bool(union_id),
            bool(open_id),
        )
        app_access_token = _exchange_app_access_token(app)
        user_id_for_detail = _resolve_userid_by_unionid_via_rest(app_access_token, union_id)
        if not user_id_for_detail:
            logger.debug("dingtalk_userid_by_unionid_failed reason=empty_userid has_unionId=%s", bool(union_id))
            raise DingTalkAPIError("Failed to resolve DingTalk userid from unionId")
        result["employeeUserId"] = user_id_for_detail

    if user_id_for_detail:
        logger.debug(
            "dingtalk_org_user_detail_start user_id=%s has_basic_email=%s",
            user_id_for_detail,
            bool(result.get("email")),
        )
        if app_access_token is None:
            app_access_token = _exchange_app_access_token(app)
        detail = _fetch_org_user_detail_via_rest(app_access_token, user_id_for_detail)
        if not detail:
            logger.debug("dingtalk_org_user_detail_failed reason=empty_detail user_id=%s", user_id_for_detail)
            raise DingTalkAPIError("Failed to get organization user detail from DingTalk")

        for key, value in detail.items():
            if value is not None:
                result[key] = value
        logger.debug(
            "dingtalk_org_user_detail_merge_success %s",
            _presence_summary(result, "employeeUserId", "openId", "name", "email", "mobile"),
        )
    else:
        logger.debug("dingtalk_org_user_detail_skipped reason=missing_lookup_user_id has_openId=%s", bool(open_id))

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
    user_id = raw.get("openId") or raw.get("userId")
    employee_user_id = raw.get("employeeUserId") or raw.get("employee_userid")

    # 部门信息处理
    dept_ids = raw.get("dept_id_list") or raw.get("deptIds") or []
    if dept_ids and not isinstance(dept_ids, list):
        dept_ids = []

    dept_names = raw.get("dept_name_list") or raw.get("dept_names") or []

    is_admin = bool(raw.get("is_admin") or raw.get("isAdmin") or False)

    email = raw.get("email") or raw.get("orgEmail")

    normalized: Dict[str, Any] = {
        "userId": user_id,
        "employeeUserId": employee_user_id,
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
