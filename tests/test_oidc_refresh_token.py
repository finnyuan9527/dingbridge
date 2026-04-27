import asyncio
import base64
import hashlib
import os
import sys
import types
import unittest
from unittest.mock import patch

# Ensure token_service can initialize in test env.
os.environ.setdefault("SECURITY__ALLOW_EPHEMERAL_KEYS", "true")

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
from app.services import oidc_store, token_service
from app.services.cache import RedisManager
from app.services.client_registry import OIDCClient
from app.services import session_service


class FakeRedis:
    def __init__(self):
        self._store: dict[str, str] = {}

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


class OIDCRefreshTokenTests(unittest.TestCase):
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
            if client_id == "other-client":
                return OIDCClient(
                    client_id="other-client",
                    client_secret="other-secret",
                    redirect_uris=["https://other.example/callback"],
                    name="other",
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
            return_value=["test-client", "other-client"],
        )
        cls._patch_oidc_client.start()
        cls._patch_idp_settings.start()
        cls._patch_enabled_client_ids.start()

        test_app = FastAPI()
        test_app.include_router(oidc.router)
        test_app.include_router(oidc.well_known_router)
        cls.client_ctx = TestClient(test_app)
        cls.client = cls.client_ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_ctx.__exit__(None, None, None)
        cls._patch_oidc_client.stop()
        cls._patch_idp_settings.stop()
        cls._patch_enabled_client_ids.stop()
        RedisManager._client = None

    def setUp(self):
        self.fake_redis._store.clear()
        self.client.cookies.clear()

    def _auth_header(self, client_id="test-client", client_secret="test-secret"):
        raw = f"{client_id}:{client_secret}".encode("utf-8")
        token = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def _issue_code(self, verifier: str) -> str:
        code = asyncio.run(
            oidc_store.issue_code(
                client_id="test-client",
                redirect_uri="https://client.example/callback",
                scope="openid profile",
                user=User(subject="u-1", name="Test User"),
                nonce="nonce-1",
                code_challenge=_pkce_s256(verifier),
                code_challenge_method="S256",
            )
        )
        return code

    def test_authorization_code_issues_refresh_token(self):
        code_verifier = "verifier-abc"
        code = self._issue_code(code_verifier)
        resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": code_verifier,
            },
            headers=self._auth_header(),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertIn("id_token", data)
        self.assertIn("refresh_token", data)
        self.assertEqual(data.get("token_type"), "Bearer")

    def test_refresh_token_success_and_rotation(self):
        code_verifier = "verifier-rotate"
        code = self._issue_code(code_verifier)
        first = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": code_verifier,
            },
            headers=self._auth_header(),
        )
        self.assertEqual(first.status_code, 200, first.text)
        first_refresh = first.json()["refresh_token"]

        second = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first_refresh,
            },
            headers=self._auth_header(),
        )
        self.assertEqual(second.status_code, 200, second.text)
        second_refresh = second.json()["refresh_token"]
        self.assertNotEqual(first_refresh, second_refresh)

        replay = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first_refresh,
            },
            headers=self._auth_header(),
        )
        self.assertEqual(replay.status_code, 400, replay.text)
        self.assertEqual(replay.json().get("detail"), "invalid_grant")

    def test_refresh_token_fails_with_client_mismatch(self):
        code_verifier = "verifier-mismatch"
        code = self._issue_code(code_verifier)
        first = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": code_verifier,
            },
            headers=self._auth_header(),
        )
        self.assertEqual(first.status_code, 200, first.text)
        refresh = first.json()["refresh_token"]

        mismatch = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            headers=self._auth_header(client_id="other-client", client_secret="other-secret"),
        )
        self.assertEqual(mismatch.status_code, 400, mismatch.text)
        self.assertEqual(mismatch.json().get("detail"), "invalid_grant")

    def test_logout_clears_session_and_revokes_refresh_token(self):
        code_verifier = "verifier-logout"
        code = self._issue_code(code_verifier)
        token_resp = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": code_verifier,
            },
            headers=self._auth_header(),
        )
        self.assertEqual(token_resp.status_code, 200, token_resp.text)
        refresh = token_resp.json()["refresh_token"]

        session_id = "sid-logout-1"
        asyncio.run(
            session_service.create_session(
                session_id,
                User(subject="u-logout", name="Logout User"),
            )
        )
        self.client.cookies.set("dingbridge_sso", session_id)

        logout_resp = self.client.post(
            "/oidc/logout",
            data={"refresh_token": refresh},
        )
        self.assertEqual(logout_resp.status_code, 200, logout_resp.text)
        self.assertEqual(logout_resp.json().get("ok"), True)

        session_user = asyncio.run(session_service.get_user_by_session(session_id))
        self.assertIsNone(session_user)

        refresh_after_logout = self.client.post(
            "/oidc/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            headers=self._auth_header(),
        )
        self.assertEqual(refresh_after_logout.status_code, 400, refresh_after_logout.text)
        self.assertEqual(refresh_after_logout.json().get("detail"), "invalid_grant")

    def test_logout_get_redirect_whitelist(self):
        session_id = "sid-logout-get-1"
        asyncio.run(
            session_service.create_session(
                session_id,
                User(subject="u-logout-get", name="Logout GET User"),
            )
        )
        self.client.cookies.set("dingbridge_sso", session_id)

        ok = self.client.get(
            "/oidc/logout",
            params={
                "client_id": "test-client",
                "post_logout_redirect_uri": "https://client.example/callback",
            },
            follow_redirects=False,
        )
        self.assertEqual(ok.status_code, 302, ok.text)
        self.assertEqual(ok.headers.get("location"), "https://client.example/callback")
        self.assertIsNone(asyncio.run(session_service.get_user_by_session(session_id)))

        bad = self.client.get(
            "/oidc/logout",
            params={
                "client_id": "test-client",
                "post_logout_redirect_uri": "https://evil.example/logout",
            },
            follow_redirects=False,
        )
        self.assertEqual(bad.status_code, 400, bad.text)
        self.assertEqual(bad.json().get("detail"), "invalid_post_logout_redirect_uri")

    def test_logout_get_supports_id_token_hint_and_state(self):
        id_token_hint = token_service.create_id_token(
            User(subject="u-hint", name="Hint User"),
            client_id="test-client",
            nonce="n-hint",
        )
        resp = self.client.get(
            "/oidc/logout",
            params={
                "id_token_hint": id_token_hint,
                "post_logout_redirect_uri": "https://client.example/callback",
                "state": "s-123",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302, resp.text)
        self.assertEqual(resp.headers.get("location"), "https://client.example/callback?state=s-123")

    def test_logout_post_rejects_mismatched_id_token_hint_client(self):
        id_token_hint = token_service.create_id_token(
            User(subject="u-hint2", name="Hint2 User"),
            client_id="test-client",
            nonce="n-hint2",
        )
        resp = self.client.post(
            "/oidc/logout",
            data={
                "client_id": "other-client",
                "id_token_hint": id_token_hint,
                "post_logout_redirect_uri": "https://other.example/callback",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json().get("detail"), "invalid_client")


if __name__ == "__main__":
    unittest.main()
