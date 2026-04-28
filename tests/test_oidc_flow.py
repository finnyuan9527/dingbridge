"""
tests/test_oidc_flow.py
覆盖 OIDC 授权码流的核心路径：
  - /oidc/authorize  参数校验（PKCE 缺失、invalid client、invalid redirect_uri）
  - /oidc/authorize  有效 session 时正常颁发 code
  - /oidc/token      authorization_code grant（PKCE 校验）
  - /oidc/token      invalid grant / 错误客户端凭证
  - /oidc/userinfo   无 token、无效 token、有效 token scope 过滤
  - OIDC Discovery   /.well-known/openid-configuration 字段完整性
"""

import asyncio
import base64
import hashlib
import os
import sys
import types
import unittest
from unittest.mock import patch

# 允许测试环境使用临时密钥
os.environ.setdefault("SECURITY__ALLOW_EPHEMERAL_KEYS", "true")

# Stub 掉钉钉适配器，避免外部 HTTP 依赖
stub_dingtalk_adapter = types.ModuleType("app.services.dingtalk_adapter")


async def _dummy_fetch_normalized_user_info(code, app):
    return {"userid": "dummy"}


stub_dingtalk_adapter.fetch_normalized_user_info = _dummy_fetch_normalized_user_info
stub_dingtalk_adapter.build_oauth_login_url = lambda state, app: "https://example.com"
sys.modules.setdefault("app.services.dingtalk_adapter", stub_dingtalk_adapter)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.user import User
from app.routers import oidc
from app.services import oidc_store, token_service, session_service
from app.services.cache import RedisManager
from app.services.client_registry import OIDCClient
from app.services.auth_orchestrator import RequireLogin


# ---------------------------------------------------------------------------
# 共用 Fake Redis（同 test_oidc_refresh_token.py 保持一致）
# ---------------------------------------------------------------------------

class FakeRedis:
    def __init__(self):
        self._store: dict = {}

    async def set(self, key, value, ex=None):
        self._store[key] = value
        return True

    async def get(self, key):
        return self._store.get(key)

    async def delete(self, key):
        self._store.pop(key, None)
        return 1

    async def eval(self, script, numkeys, key):
        value = self._store.get(key)
        if value is not None:
            self._store.pop(key, None)
        return value

    async def ping(self):
        return True

    async def close(self):
        return None


class _FakeIdPSettings:
    oidc_issuer = "http://testserver"
    oidc_id_token_exp_minutes = 60
    oidc_access_token_exp_minutes = 30


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# 测试套件
# ---------------------------------------------------------------------------

class OIDCFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake_redis = FakeRedis()
        RedisManager._client = cls.fake_redis

        def _mock_get_oidc_client(client_id: str):
            if client_id == "test-client":
                return OIDCClient(
                    client_id="test-client",
                    client_secret="test-secret",
                    redirect_uris=["https://client.example/callback"],
                    name="test",
                    enabled=True,
                )
            return None

        cls._patch_oidc_client = patch(
            "app.services.client_registry.ClientRegistry.get_oidc_client",
            side_effect=_mock_get_oidc_client,
        )
        cls._patch_idp_settings = patch(
            "app.services.client_registry.ClientRegistry.get_idp_settings",
            return_value=_FakeIdPSettings(),
        )
        cls._patch_enabled_client_ids = patch(
            "app.services.client_registry.ClientRegistry.get_all_enabled_oidc_client_ids",
            return_value=["test-client"],
        )
        # userinfo 端点的 decode_and_verify_bearer 需要 issuer 匹配
        cls._patch_issuer = patch(
            "app.services.token_service._issuer",
            return_value="http://testserver",
        )
        cls._patch_oidc_client.start()
        cls._patch_idp_settings.start()
        cls._patch_enabled_client_ids.start()
        cls._patch_issuer.start()

        test_app = FastAPI()
        test_app.include_router(oidc.router)
        test_app.include_router(oidc.well_known_router)

        @test_app.exception_handler(RequireLogin)
        async def _require_login_handler(request, exc):
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=exc.redirect_to, status_code=302)

        cls.client_ctx = TestClient(test_app, raise_server_exceptions=False)
        cls.client = cls.client_ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_ctx.__exit__(None, None, None)
        cls._patch_oidc_client.stop()
        cls._patch_idp_settings.stop()
        cls._patch_enabled_client_ids.stop()
        cls._patch_issuer.stop()
        RedisManager._client = None

    def setUp(self):
        self.fake_redis._store.clear()
        self.client.cookies.clear()

    def _auth_header(self, client_id="test-client", client_secret="test-secret"):
        raw = f"{client_id}:{client_secret}".encode("utf-8")
        token = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    # ------------------------------------------------------------------
    # OIDC Discovery
    # ------------------------------------------------------------------

    def test_openid_configuration_fields(self):
        resp = self.client.get("/.well-known/openid-configuration")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in (
            "issuer",
            "authorization_endpoint",
            "token_endpoint",
            "userinfo_endpoint",
            "jwks_uri",
            "response_types_supported",
            "grant_types_supported",
            "scopes_supported",
        ):
            self.assertIn(key, data, f"Missing field: {key}")
        self.assertIn("code", data["response_types_supported"])
        self.assertIn("authorization_code", data["grant_types_supported"])
        self.assertIn("refresh_token", data["grant_types_supported"])

    # ------------------------------------------------------------------
    # /oidc/authorize — 参数校验
    # ------------------------------------------------------------------

    def _authorize_params(self, **overrides):
        verifier = "test-verifier-1234"
        base = {
            "response_type": "code",
            "client_id": "test-client",
            "redirect_uri": "https://client.example/callback",
            "scope": "openid profile",
            "code_challenge": _pkce_s256(verifier),
            "code_challenge_method": "S256",
        }
        base.update(overrides)
        return base

    def test_authorize_rejects_missing_pkce(self):
        params = self._authorize_params()
        del params["code_challenge"]
        resp = self.client.get("/oidc/authorize", params=params, follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_request")

    def test_authorize_rejects_plain_pkce_method(self):
        params = self._authorize_params(code_challenge_method="plain")
        resp = self.client.get("/oidc/authorize", params=params, follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_code_challenge_method")

    def test_authorize_rejects_invalid_client(self):
        params = self._authorize_params(client_id="nonexistent-client")
        resp = self.client.get("/oidc/authorize", params=params, follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_client")

    def test_authorize_rejects_invalid_redirect_uri(self):
        params = self._authorize_params(redirect_uri="https://evil.example/callback")
        resp = self.client.get("/oidc/authorize", params=params, follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_redirect_uri")

    def test_authorize_rejects_missing_openid_scope(self):
        params = self._authorize_params(scope="profile")
        resp = self.client.get("/oidc/authorize", params=params, follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_scope")

    def test_authorize_rejects_unsupported_response_type(self):
        params = self._authorize_params(response_type="token")
        resp = self.client.get("/oidc/authorize", params=params, follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "unsupported_response_type")

    def test_authorize_redirects_to_dingtalk_when_no_session(self):
        """无 SSO session 时应重定向到 DingTalk 登录"""
        params = self._authorize_params()
        resp = self.client.get("/oidc/authorize", params=params, follow_redirects=False)
        # RequireLogin 触发 302 到 /dingtalk/login
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/dingtalk/login", resp.headers["location"])

    def test_authorize_issues_code_with_valid_session(self):
        """有效 SSO session 时应直接颁发 authorization code"""
        session_id = "sid-auth-flow-1"
        asyncio.run(
            session_service.create_session(
                session_id,
                User(subject="u-flow", name="Flow User"),
            )
        )
        self.client.cookies.set("dingbridge_sso", session_id)

        verifier = "flow-verifier-xyz"
        params = self._authorize_params(code_challenge=_pkce_s256(verifier), state="st-abc")
        resp = self.client.get("/oidc/authorize", params=params, follow_redirects=False)

        self.assertEqual(resp.status_code, 302)
        location = resp.headers["location"]
        self.assertIn("https://client.example/callback", location)
        self.assertIn("code=", location)
        self.assertIn("state=st-abc", location)

    def test_authorize_ignores_form_post_and_still_redirects_with_query_params(self):
        session_id = "sid-auth-form-post"
        asyncio.run(
            session_service.create_session(
                session_id,
                User(subject="u-form-post", name="Form Post User"),
            )
        )
        self.client.cookies.set("dingbridge_sso", session_id)

        verifier = "flow-verifier-form-post"
        params = self._authorize_params(
            code_challenge=_pkce_s256(verifier),
            state="st-form-post",
            response_mode="form_post",
        )
        resp = self.client.get("/oidc/authorize", params=params, follow_redirects=False)

        self.assertEqual(resp.status_code, 302)
        location = resp.headers["location"]
        self.assertIn("https://client.example/callback", location)
        self.assertIn("code=", location)
        self.assertIn("state=st-form-post", location)

    # ------------------------------------------------------------------
    # /oidc/token — authorization_code grant
    # ------------------------------------------------------------------

    def _issue_code(self, verifier: str, user: User | None = None) -> str:
        return asyncio.run(
            oidc_store.issue_code(
                client_id="test-client",
                redirect_uri="https://client.example/callback",
                scope="openid profile email",
                user=user or User(subject="u-token", name="Token User", email="token@example.com"),
                nonce="nonce-token",
                code_challenge=_pkce_s256(verifier),
                code_challenge_method="S256",
            )
        )

    def test_token_authorization_code_success(self):
        verifier = "tok-verifier-1"
        code = self._issue_code(verifier)
        resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": verifier,
            },
            headers=self._auth_header(),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertIn("id_token", data)
        self.assertIn("refresh_token", data)
        self.assertEqual(data["token_type"], "Bearer")
        self.assertIn("expires_in", data)

    def test_token_supports_client_secret_post(self):
        verifier = "tok-verifier-post"
        code = self._issue_code(verifier)
        resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": verifier,
                "client_id": "test-client",
                "client_secret": "test-secret",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("access_token", resp.json())

    def test_token_rejects_missing_redirect_uri_for_authorization_code(self):
        verifier = "tok-verifier-no-redirect"
        code = self._issue_code(verifier)
        resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            },
            headers=self._auth_header(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_request")

    def test_token_rejects_missing_code_verifier_when_pkce_was_used(self):
        verifier = "tok-verifier-missing-pkce"
        code = self._issue_code(verifier)
        resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/callback",
            },
            headers=self._auth_header(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_request")

    def test_token_rejects_invalid_pkce_verifier(self):
        verifier = "tok-verifier-2"
        code = self._issue_code(verifier)
        resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": "wrong-verifier",
            },
            headers=self._auth_header(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_grant")

    def test_token_rejects_code_replay(self):
        verifier = "tok-verifier-3"
        code = self._issue_code(verifier)
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://client.example/callback",
            "code_verifier": verifier,
        }
        resp1 = self.client.post("/oidc/token", data=data, headers=self._auth_header())
        self.assertEqual(resp1.status_code, 200, resp1.text)

        # 重放同一个 code
        resp2 = self.client.post("/oidc/token", data=data, headers=self._auth_header())
        self.assertEqual(resp2.status_code, 400)
        self.assertEqual(resp2.json().get("detail"), "invalid_grant")

    def test_token_rejects_wrong_client_secret(self):
        verifier = "tok-verifier-4"
        code = self._issue_code(verifier)
        resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": verifier,
            },
            headers=self._auth_header(client_secret="wrong-secret"),
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json().get("detail"), "invalid_client_secret")

    def test_token_rejects_redirect_uri_mismatch(self):
        verifier = "tok-verifier-5"
        code = self._issue_code(verifier)
        resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://evil.example/callback",
                "code_verifier": verifier,
            },
            headers=self._auth_header(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_grant")

    def test_token_rejects_unsupported_grant_type(self):
        resp = self.client.post(
            "/oidc/token",
            data={"grant_type": "password"},
            headers=self._auth_header(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "unsupported_grant_type")

    # ------------------------------------------------------------------
    # /oidc/userinfo — scope 过滤
    # ------------------------------------------------------------------

    def _get_access_token(self, scope="openid profile email phone") -> str:
        user = User(
            subject="u-info",
            name="Info User",
            email="info@example.com",
            phone_number="+861234567890",
        )
        return token_service.create_access_token(user, client_id="test-client", scope=scope)

    def test_userinfo_rejects_missing_bearer(self):
        resp = self.client.get("/oidc/userinfo")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json().get("detail"), "missing_bearer_token")

    def test_userinfo_rejects_invalid_token(self):
        resp = self.client.get("/oidc/userinfo", headers={"Authorization": "Bearer invalid.token.here"})
        self.assertEqual(resp.status_code, 500)  # jose 抛出异常，FastAPI 默认返回 500

    def test_userinfo_returns_sub_only_for_openid_scope(self):
        token = self._get_access_token(scope="openid")
        resp = self.client.get("/oidc/userinfo", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("sub", data)
        self.assertNotIn("name", data)
        self.assertNotIn("email", data)
        self.assertNotIn("phone_number", data)

    def test_userinfo_returns_profile_fields(self):
        token = self._get_access_token(scope="openid profile")
        resp = self.client.get("/oidc/userinfo", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("name", data)
        self.assertEqual(data["name"], "Info User")
        self.assertNotIn("email", data)

    def test_userinfo_returns_email_and_phone_with_scopes(self):
        token = self._get_access_token(scope="openid profile email phone")
        resp = self.client.get("/oidc/userinfo", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("email"), "info@example.com")
        self.assertEqual(data.get("phone_number"), "+861234567890")

    # ------------------------------------------------------------------
    # /oidc/logout — 互操作与 redirect 校验
    # ------------------------------------------------------------------

    def test_logout_redirects_with_state_when_post_logout_redirect_uri_is_valid(self):
        resp = self.client.post(
            "/oidc/logout",
            data={
                "client_id": "test-client",
                "post_logout_redirect_uri": "https://client.example/callback",
                "state": "logout-state-1",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("https://client.example/callback", resp.headers["location"])
        self.assertIn("state=logout-state-1", resp.headers["location"])

    def test_logout_rejects_invalid_post_logout_redirect_uri(self):
        resp = self.client.post(
            "/oidc/logout",
            data={
                "client_id": "test-client",
                "post_logout_redirect_uri": "https://evil.example/logout",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_post_logout_redirect_uri")

    def test_logout_resolves_client_from_id_token_hint(self):
        user = User(subject="u-logout-hint", name="Logout Hint User")
        id_token_hint = token_service.create_id_token(
            user,
            client_id="test-client",
            nonce="logout-nonce",
        )
        resp = self.client.post(
            "/oidc/logout",
            data={
                "id_token_hint": id_token_hint,
                "post_logout_redirect_uri": "https://client.example/callback",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("https://client.example/callback", resp.headers["location"])

    def test_logout_rejects_invalid_id_token_hint(self):
        resp = self.client.post(
            "/oidc/logout",
            data={
                "id_token_hint": "not-a-jwt",
                "post_logout_redirect_uri": "https://client.example/callback",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "invalid_id_token_hint")


if __name__ == "__main__":
    unittest.main()
