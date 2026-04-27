import os


os.environ.setdefault("SECURITY__ALLOW_EPHEMERAL_KEYS", "true")

from app.config import DingTalkSettings, Settings


def test_removed_protocol_settings_are_not_exposed():
    assert "saml" not in Settings.model_fields


def test_dingtalk_settings_expose_only_used_endpoint_overrides():
    assert "auth_base_url" in DingTalkSettings.model_fields
    assert "token_base_url" in DingTalkSettings.model_fields
    assert "user_info_url" not in DingTalkSettings.model_fields
