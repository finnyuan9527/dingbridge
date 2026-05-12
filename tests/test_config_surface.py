import os
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
