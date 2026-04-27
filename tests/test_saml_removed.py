import sys
import types


stub_dingtalk_adapter = types.ModuleType("app.services.dingtalk_adapter")
stub_dingtalk_adapter.fetch_normalized_user_info = None
stub_dingtalk_adapter.build_oauth_login_url = lambda state, app: "https://example.com"
sys.modules.setdefault("app.services.dingtalk_adapter", stub_dingtalk_adapter)

from app.main import create_app


def test_saml_routes_are_not_registered():
    app = create_app()
    paths = {getattr(route, "path", "") for route in app.routes}

    assert not any(path.startswith("/saml") for path in paths)
    assert "/admin/saml-sps" not in paths
