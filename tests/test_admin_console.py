import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("SECURITY__ALLOW_EPHEMERAL_KEYS", "true")

stub_dingtalk_adapter = types.ModuleType("app.services.dingtalk_adapter")
stub_dingtalk_adapter.fetch_normalized_user_info = MagicMock()
stub_dingtalk_adapter.build_oauth_login_url = MagicMock(return_value="https://example.com")
sys.modules.setdefault("app.services.dingtalk_adapter", stub_dingtalk_adapter)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import admin


class AdminConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_app = FastAPI()
        test_app.include_router(admin.router)
        cls.client_ctx = TestClient(test_app, raise_server_exceptions=False)
        cls.client = cls.client_ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_ctx.__exit__(None, None, None)

    def test_oidc_client_console_page_renders(self):
        resp = self.client.get("/admin/console/oidc-clients")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("OIDC Client Console", resp.text)
        self.assertIn("Admin API Key", resp.text)
        self.assertIn("/admin/oidc-clients", resp.text)
        self.assertIn("/admin/dingtalk-apps", resp.text)

    def test_oidc_client_console_page_exposes_editor_fields(self):
        resp = self.client.get("/admin/console/oidc-clients")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("client_id", resp.text)
        self.assertIn("client_secret", resp.text)
        self.assertIn("redirect_uris", resp.text)
        self.assertIn("require_pkce", resp.text)
        self.assertIn("dingtalk_app_id", resp.text)

    def test_oidc_client_console_page_references_static_assets(self):
        resp = self.client.get("/admin/console/oidc-clients")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("/static/admin/oidc_clients.css", resp.text)
        self.assertIn("/static/admin/oidc_clients.js", resp.text)
        self.assertIn("/static/admin/oidc_clients.css?v=", resp.text)
        self.assertIn("/static/admin/oidc_clients.js?v=", resp.text)

    def test_oidc_client_console_script_builds_table_with_dom_nodes(self):
        script = Path("app/static/admin/oidc_clients.js").read_text(encoding="utf-8")
        self.assertIn('document.createElement("tr")', script)
        self.assertIn(".textContent =", script)
        self.assertNotIn("rowsEl.innerHTML = clients.map", script)

    def test_oidc_client_console_script_freezes_client_id_during_edit(self):
        script = Path("app/static/admin/oidc_clients.js").read_text(encoding="utf-8")
        self.assertIn("clientIdEl.readOnly = isEditing;", script)
        self.assertIn("payloadClientId = editingClientId || clientIdEl.value.trim();", script)

    def test_oidc_client_console_script_handles_require_pkce(self):
        script = Path("app/static/admin/oidc_clients.js").read_text(encoding="utf-8")
        self.assertIn('document.getElementById("require_pkce")', script)
        self.assertIn("requirePkceEl.checked = client.require_pkce !== false;", script)
        self.assertIn("require_pkce: requirePkceEl.checked", script)

    def test_oidc_client_console_page_uses_control_bar_layout(self):
        resp = self.client.get("/admin/console/oidc-clients")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("control-bar", resp.text)
        self.assertIn("workspace", resp.text)
        self.assertIn("editor-panel", resp.text)
        self.assertIn("browser-panel", resp.text)

    def test_oidc_client_console_page_groups_editor_sections(self):
        resp = self.client.get("/admin/console/oidc-clients")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("Identity", resp.text)
        self.assertIn("Security", resp.text)
        self.assertIn("Access", resp.text)


if __name__ == "__main__":
    unittest.main()
