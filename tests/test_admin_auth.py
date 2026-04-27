"""
tests/test_admin_auth.py
覆盖 Admin API 鉴权：
  - 无 key 时所有接口返回 403
  - 错误 key 时返回 403
  - 正确 key 时正常响应（不依赖真实 DB）
  - 统一错误响应（不暴露"未配置"和"密钥错误"的区别）
"""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECURITY__ALLOW_EPHEMERAL_KEYS", "true")

# Stub 掉钉钉适配器
stub_dingtalk_adapter = types.ModuleType("app.services.dingtalk_adapter")
stub_dingtalk_adapter.fetch_normalized_user_info = MagicMock()
stub_dingtalk_adapter.build_oauth_login_url = MagicMock(return_value="https://example.com")
sys.modules.setdefault("app.services.dingtalk_adapter", stub_dingtalk_adapter)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import admin
from app.services.client_registry import IdPSettings


# ---------------------------------------------------------------------------
# 共用 Fake DB session（最小实现）
# ---------------------------------------------------------------------------

class _FakeIdPSettingsORM:
    id = 1
    oidc_issuer = "http://testserver"
    oidc_id_token_exp_minutes = 60


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, model, pk):
        return _FakeIdPSettingsORM()

    def execute(self, stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.scalars.return_value.first.return_value = None
        return result

    def add(self, obj):
        pass

    def flush(self):
        pass


def _fake_get_session():
    return _FakeSession()


# ---------------------------------------------------------------------------
# 测试套件
# ---------------------------------------------------------------------------

class AdminAuthTests(unittest.TestCase):
    """验证 Admin API 在不同 key 配置下的鉴权行为。"""

    # PUT / POST 接口在 FastAPI 中 body validation 优先于 dependency 执行，
    # 若 body 缺失，FastAPI 返回 422 而非 403。
    # 因此这里只测试 GET 端点（鉴权生效前不需要 body）。
    _ADMIN_GET_ENDPOINTS = [
        ("GET", "/admin/idp-settings"),
        ("GET", "/admin/dingtalk-apps"),
        ("GET", "/admin/oidc-clients"),
        ("POST", "/admin/reload"),
    ]

    @classmethod
    def setUpClass(cls):
        test_app = FastAPI()
        test_app.include_router(admin.router)
        cls.client_ctx = TestClient(test_app, raise_server_exceptions=False)
        cls.client = cls.client_ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_ctx.__exit__(None, None, None)

    def _request(self, method: str, path: str, headers: dict | None = None):
        return self.client.request(method, path, headers=headers or {})

    # ------------------------------------------------------------------
    # 场景 1：admin_api_key 未配置
    # ------------------------------------------------------------------

    def test_no_key_configured_returns_403_for_all_endpoints(self):
        """当 SECURITY__ADMIN_API_KEY 未配置时，所有 admin 接口一律返回 403。"""
        with patch("app.config.settings.security.admin_api_key", ""):
            for method, path in self._ADMIN_GET_ENDPOINTS:
                with self.subTest(method=method, path=path):
                    resp = self._request(method, path)
                    self.assertEqual(resp.status_code, 403, f"{method} {path}: {resp.text}")

    def test_no_key_configured_response_detail_is_forbidden(self):
        """未配置时错误响应与密钥错误响应保持一致（不暴露状态差异）。"""
        with patch("app.config.settings.security.admin_api_key", ""):
            resp = self._request("GET", "/admin/idp-settings")
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(resp.json().get("detail"), "forbidden")

    # ------------------------------------------------------------------
    # 场景 2：提供错误 key
    # ------------------------------------------------------------------

    def test_wrong_key_returns_403(self):
        """提供错误 key 时所有 admin 接口返回 403，与未配置响应一致。"""
        with patch("app.config.settings.security.admin_api_key", "correct-key"):
            for method, path in self._ADMIN_GET_ENDPOINTS:
                with self.subTest(method=method, path=path):
                    resp = self._request(method, path, headers={"x-admin-key": "wrong-key"})
                    self.assertEqual(resp.status_code, 403, f"{method} {path}: {resp.text}")
                    self.assertEqual(resp.json().get("detail"), "forbidden")

    def test_no_key_header_with_configured_key_returns_403(self):
        """key 已配置但请求不携带 header 时，返回 403。"""
        with patch("app.config.settings.security.admin_api_key", "some-key"):
            resp = self._request("GET", "/admin/idp-settings")
            self.assertEqual(resp.status_code, 403)

    # ------------------------------------------------------------------
    # 场景 3：提供正确 key
    # ------------------------------------------------------------------

    def test_correct_key_allows_get_idp_settings(self):
        """正确 key 时 GET /admin/idp-settings 应返回 200。"""
        fake_idp = IdPSettings(
            oidc_issuer="http://testserver",
            oidc_id_token_exp_minutes=60,
            oidc_access_token_exp_minutes=30,
        )
        with (
            patch("app.config.settings.security.admin_api_key", "real-key"),
            patch(
                "app.services.client_registry.ClientRegistry.get_idp_settings",
                return_value=fake_idp,
            ),
        ):
            resp = self._request("GET", "/admin/idp-settings", headers={"x-admin-key": "real-key"})
            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()
            self.assertIn("oidc_issuer", data)
            self.assertIn("oidc_id_token_exp_minutes", data)

    def test_correct_key_allows_list_dingtalk_apps(self):
        """正确 key 时 GET /admin/dingtalk-apps 应返回 200 空列表。"""
        with (
            patch("app.config.settings.security.admin_api_key", "real-key"),
            patch("app.routers.admin.get_session", _fake_get_session),
        ):
            resp = self._request("GET", "/admin/dingtalk-apps", headers={"x-admin-key": "real-key"})
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertIsInstance(resp.json(), list)

    def test_correct_key_allows_list_oidc_clients(self):
        """正确 key 时 GET /admin/oidc-clients 应返回 200 空列表。"""
        with (
            patch("app.config.settings.security.admin_api_key", "real-key"),
            patch("app.routers.admin.get_session", _fake_get_session),
        ):
            resp = self._request("GET", "/admin/oidc-clients", headers={"x-admin-key": "real-key"})
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertIsInstance(resp.json(), list)

    def test_correct_key_allows_reload(self):
        """正确 key 时 POST /admin/reload 应返回 200。"""
        with (
            patch("app.config.settings.security.admin_api_key", "real-key"),
            patch("app.services.client_registry.ClientRegistry.reload"),
        ):
            resp = self._request("POST", "/admin/reload", headers={"x-admin-key": "real-key"})
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(resp.json().get("ok"), True)

    # ------------------------------------------------------------------
    # 场景 4：时序安全（常量时间比较）
    # ------------------------------------------------------------------

    def test_hmac_compare_digest_is_used(self):
        """确认 _require_admin_key 使用 hmac.compare_digest 而非 == 操作符。"""
        import inspect
        import app.routers.admin as admin_module
        src = inspect.getsource(admin_module._require_admin_key)
        self.assertIn("compare_digest", src, "应使用 hmac.compare_digest 防止时序攻击")
        self.assertNotIn("x_admin_key !=", src, "不应使用 != 直接比较")


if __name__ == "__main__":
    unittest.main()
