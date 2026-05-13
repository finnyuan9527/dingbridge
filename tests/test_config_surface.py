import os
import asyncio
import importlib.util
import io
import logging
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("SECURITY__ALLOW_EPHEMERAL_KEYS", "true")

from app.config import DingTalkSettings, Settings
from app.logging_config import configure_logging


def _load_real_dingtalk_adapter():
    module_path = Path("app/services/dingtalk_adapter.py")
    spec = importlib.util.spec_from_file_location("real_dingtalk_adapter_for_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_removed_protocol_settings_are_not_exposed():
    assert "saml" not in Settings.model_fields


def test_dingtalk_settings_expose_only_used_endpoint_overrides():
    assert "auth_base_url" in DingTalkSettings.model_fields
    assert "token_base_url" in DingTalkSettings.model_fields
    assert "user_info_url" not in DingTalkSettings.model_fields


def test_compose_publishes_redis_to_loopback_only():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    redis_section = compose.split("  redis:", 1)[1]
    assert '"127.0.0.1:6379:6379"' in redis_section
    assert '\n      - "6379:6379"' not in redis_section


def test_logging_settings_control_application_logger_level():
    settings = Settings(
        logging={
            "level": "DEBUG",
        }
    )

    configure_logging(settings)

    assert logging.getLogger("dingbridge").level == logging.DEBUG


def test_dingtalk_basic_exception_log_includes_debug_details(monkeypatch):
    dingtalk_adapter = _load_real_dingtalk_adapter()

    def raise_request_error(*args, **kwargs):
        raise RuntimeError("dingtalk api unavailable")

    monkeypatch.setattr(dingtalk_adapter.httpx, "get", raise_request_error)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    target_logger = logging.getLogger("dingbridge.dingtalk")
    previous_level = target_logger.level
    previous_disabled = target_logger.disabled
    target_logger.disabled = False
    target_logger.setLevel(logging.DEBUG)
    target_logger.addHandler(handler)
    try:
        result = dingtalk_adapter._fetch_user_basic_info_via_rest("user-token")
    finally:
        target_logger.removeHandler(handler)
        target_logger.setLevel(previous_level)
        target_logger.disabled = previous_disabled

    assert result is None
    logs = stream.getvalue()
    assert "dingtalk_user_basic_exception error_type=RuntimeError" in logs
    assert "dingtalk api unavailable" in logs


def test_dingtalk_basic_http_failure_logs_response_details(monkeypatch):
    dingtalk_adapter = _load_real_dingtalk_adapter()
    request = dingtalk_adapter.httpx.Request("GET", "https://api.dingtalk.com/v1.0/contact/users/me")
    response = dingtalk_adapter.httpx.Response(
        403,
        json={
            "code": "Forbidden.AccessDenied.AccessTokenPermissionDenied",
            "requestid": "req-1",
            "message": "missing permission",
        },
        request=request,
        headers={"x-acs-request-id": "header-req-1"},
    )

    monkeypatch.setattr(dingtalk_adapter.httpx, "get", lambda *args, **kwargs: response)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    target_logger = logging.getLogger("dingbridge.dingtalk")
    previous_level = target_logger.level
    previous_disabled = target_logger.disabled
    target_logger.disabled = False
    target_logger.setLevel(logging.DEBUG)
    target_logger.addHandler(handler)
    try:
        result = dingtalk_adapter._fetch_user_basic_info_via_rest("user-token")
    finally:
        target_logger.removeHandler(handler)
        target_logger.setLevel(previous_level)
        target_logger.disabled = previous_disabled

    assert result is None
    logs = stream.getvalue()
    assert "dingtalk_user_basic_request_start endpoint=/v1.0/contact/users/me" in logs
    assert "dingtalk_user_basic_response status_code=403 request_id=header-req-1" in logs
    assert "dingtalk_user_basic_result ok=false body=" in logs
    assert "Forbidden.AccessDenied.AccessTokenPermissionDenied" in logs


def test_dingtalk_debug_dump_redacts_tokens_and_profile_fields():
    dingtalk_adapter = _load_real_dingtalk_adapter()

    dump = dingtalk_adapter._debug_dump_value(
        {
            "access_token": "secret-token",
            "refreshToken": "secret-refresh",
            "userid": "user-1",
            "unionid": "union-1",
            "email": "alice@example.com",
            "orgEmail": "alice@corp.example.com",
            "mobile": "+8613000000000",
            "dept_names": ["IT"],
            "deptNames": ["Finance"],
            "phoneNumber": "+8613999999999",
            "nested": [{"client_secret": "secret-client", "name": "Alice"}],
        }
    )

    assert dump["access_token"] == "***REDACTED***"
    assert dump["refreshToken"] == "***REDACTED***"
    assert dump["nested"][0]["client_secret"] == "***REDACTED***"
    assert dump["userid"] == "user-1"
    assert dump["unionid"] == "union-1"
    assert dump["email"] == "***REDACTED***"
    assert dump["orgEmail"] == "***REDACTED***"
    assert dump["mobile"] == "***REDACTED***"
    assert dump["dept_names"] == "***REDACTED***"
    assert dump["deptNames"] == "***REDACTED***"
    assert dump["phoneNumber"] == "***REDACTED***"
    assert dump["nested"][0]["name"] == "***REDACTED***"


def test_dingtalk_user_info_still_enriches_when_detail_fetch_disabled(monkeypatch):
    dingtalk_adapter = _load_real_dingtalk_adapter()
    app = SimpleNamespace(fetch_user_details=False)

    def fail_if_sdk_detail_is_called(*args, **kwargs):
        raise AssertionError("SDK detail lookup should be skipped")

    monkeypatch.setattr(dingtalk_adapter, "_exchange_user_access_token", lambda code, app: "user-token")
    monkeypatch.setattr(dingtalk_adapter, "_fetch_user_detail_via_sdk", fail_if_sdk_detail_is_called)
    monkeypatch.setattr(
        dingtalk_adapter,
        "_fetch_user_basic_info_via_rest",
        lambda token: {"openId": "open-1", "unionid": "union-1", "name": "Alice"},
    )
    monkeypatch.setattr(
        dingtalk_adapter,
        "_enrich_with_oapi",
        lambda result, union_id, app: {**result, "userid": "user-1", "org_email": "alice@example.com"},
    )

    result = dingtalk_adapter._get_user_info_sync("auth-code", app)

    assert result["unionid"] == "union-1"
    assert result["org_email"] == "alice@example.com"


def test_dingtalk_callback_orchestrator_logs_each_success_boundary(monkeypatch):
    from app.services import auth_orchestrator

    app = SimpleNamespace(
        id=1,
        name="OpenChat",
        enabled=True,
        is_default=False,
        app_key="ding-app-key",
        callback_url="https://sso.example.com/dingtalk/callback",
        fetch_user_details=True,
    )

    async def fetch_normalized_user_info(code, selected_app):
        assert code == "auth-code"
        assert selected_app is app
        return {
            "userId": "user-1",
            "unionId": "union-1",
            "name": "Alice",
            "email": "alice@example.com",
            "deptIds": [1],
            "dept_names": ["IT"],
        }

    monkeypatch.setattr(
        auth_orchestrator.client_registry.ClientRegistry,
        "get_dingtalk_app_for_oidc_client",
        lambda client_id: app,
    )
    monkeypatch.setattr(auth_orchestrator.dingtalk_adapter, "fetch_normalized_user_info", fetch_normalized_user_info)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    target_logger = logging.getLogger("dingbridge.dingtalk")
    previous_level = target_logger.level
    previous_disabled = target_logger.disabled
    target_logger.disabled = False
    target_logger.setLevel(logging.DEBUG)
    target_logger.addHandler(handler)
    try:
        user = asyncio.run(auth_orchestrator.handle_dingtalk_callback("auth-code", client_id="openchat-client-id"))
    finally:
        target_logger.removeHandler(handler)
        target_logger.setLevel(previous_level)
        target_logger.disabled = previous_disabled

    assert user.subject == "union-1"
    assert user.email == "alice@example.com"
    logs = stream.getvalue()
    assert "dingtalk_callback_orchestrator_start client_id=openchat-client-id" in logs
    assert "dingtalk_callback_orchestrator_app_selected client_id=openchat-client-id" in logs
    assert "dingtalk_callback_orchestrator_userinfo_success client_id=openchat-client-id" in logs
    assert "dingtalk_identity_mapping_result subject=union-1" in logs
    assert "dingtalk_callback_orchestrator_mapping_success client_id=openchat-client-id" in logs
