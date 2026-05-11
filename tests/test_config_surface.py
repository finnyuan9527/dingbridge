import os
from pathlib import Path


os.environ.setdefault("SECURITY__ALLOW_EPHEMERAL_KEYS", "true")

from app.config import DingTalkSettings, Settings


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
