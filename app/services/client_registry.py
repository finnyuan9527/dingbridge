import logging
import threading
import time
from typing import Dict, Optional

from pydantic import AnyHttpUrl, BaseModel

from app.config import settings
from app.db.migrations import ensure_schema_current
from app.services import config_store


logger = logging.getLogger("dingbridge.dingtalk")


class OIDCClient(BaseModel):
    client_id: str
    client_secret: str
    redirect_uris: list[str]
    require_pkce: bool = True
    name: str = ""
    enabled: bool = True
    dingtalk_app_id: int | None = None


class IdPSettings(BaseModel):
    oidc_issuer: AnyHttpUrl
    oidc_id_token_exp_minutes: int = 60
    oidc_access_token_exp_minutes: int = 30


class DingTalkApp(BaseModel):
    id: int
    name: str = ""
    enabled: bool = True
    is_default: bool = False
    app_key: str
    app_secret: str
    callback_url: AnyHttpUrl
    fetch_user_details: bool = True


def _dingtalk_app_debug(app: DingTalkApp) -> dict:
    return {
        "id": app.id,
        "name": app.name,
        "enabled": app.enabled,
        "is_default": app.is_default,
        "app_key": app.app_key,
        "callback_url": str(app.callback_url),
        "fetch_user_details": app.fetch_user_details,
    }


def _oidc_client_debug(client: OIDCClient) -> dict:
    return {
        "client_id": client.client_id,
        "enabled": client.enabled,
        "require_pkce": client.require_pkce,
        "dingtalk_app_id": client.dingtalk_app_id,
        "redirect_uri_count": len(client.redirect_uris),
    }


class ClientRegistry:
    _oidc_clients: Dict[str, OIDCClient] = {}
    _dingtalk_apps: Dict[int, DingTalkApp] = {}
    _default_dingtalk_app_id: int | None = None
    _idp_settings: IdPSettings | None = None
    _loaded_at: float | None = None
    _cache_ttl_seconds: int = 30
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def _load_from_settings(cls):
        """构建配置快照（不直接修改类变量，由调用者原子替换）。"""
        idp_settings = IdPSettings(
            oidc_issuer=settings.oidc.issuer,
            oidc_id_token_exp_minutes=settings.oidc.id_token_exp_minutes,
            oidc_access_token_exp_minutes=settings.oidc.access_token_exp_minutes,
        )

        oidc_clients: Dict[str, OIDCClient] = {}
        if settings.oidc.client_id:
            oidc_clients[settings.oidc.client_id] = OIDCClient(
                client_id=settings.oidc.client_id,
                client_secret=settings.oidc.client_secret,
                redirect_uris=[str(settings.oidc.redirect_uri)],
                require_pkce=True,
                name="Default OIDC Client",
                enabled=True,
                dingtalk_app_id=None,
            )
        
        dingtalk_apps: Dict[int, DingTalkApp] = {}
        default_dingtalk_app_id: int | None = None
        if settings.dingtalk.app_key and settings.dingtalk.app_secret:
            dingtalk_apps[0] = DingTalkApp(
                id=0,
                name="Default DingTalk App",
                enabled=True,
                is_default=True,
                app_key=settings.dingtalk.app_key,
                app_secret=settings.dingtalk.app_secret,
                callback_url=settings.dingtalk.callback_url,
                fetch_user_details=settings.dingtalk.fetch_user_details,
            )
            default_dingtalk_app_id = 0

        # 原子替换所有类变量
        cls._idp_settings = idp_settings
        cls._oidc_clients = oidc_clients
        cls._dingtalk_apps = dingtalk_apps
        cls._default_dingtalk_app_id = default_dingtalk_app_id
        cls._loaded_at = time.time()
        logger.debug(
            "client_registry_loaded source=settings apps=%r default_dingtalk_app_id=%s oidc_clients=%r",
            [_dingtalk_app_debug(app) for app in dingtalk_apps.values()],
            default_dingtalk_app_id,
            [_oidc_client_debug(client) for client in oidc_clients.values()],
        )

    @classmethod
    def _load_from_db(cls):
        ensure_schema_current()
        config_store.seed_defaults_if_needed()

        idp_raw = config_store.load_idp_settings()
        idp_settings = IdPSettings(
            oidc_issuer=idp_raw.oidc_issuer,
            oidc_id_token_exp_minutes=idp_raw.oidc_id_token_exp_minutes,
            oidc_access_token_exp_minutes=settings.oidc.access_token_exp_minutes,
        )

        apps = config_store.load_dingtalk_apps()
        dingtalk_apps = {k: DingTalkApp.model_validate(v.model_dump()) for k, v in apps.items()}
        default_dingtalk_app_id = config_store.get_default_dingtalk_app_id(apps)

        oidc_clients: Dict[str, OIDCClient] = {}
        for cid, raw in config_store.load_oidc_clients().items():
            oidc_clients[cid] = OIDCClient.model_validate(raw)

        # 原子替换所有类变量
        cls._idp_settings = idp_settings
        cls._oidc_clients = oidc_clients
        cls._dingtalk_apps = dingtalk_apps
        cls._default_dingtalk_app_id = default_dingtalk_app_id
        cls._loaded_at = time.time()
        logger.debug(
            "client_registry_loaded source=db apps=%r default_dingtalk_app_id=%s oidc_clients=%r",
            [_dingtalk_app_debug(app) for app in dingtalk_apps.values()],
            default_dingtalk_app_id,
            [_oidc_client_debug(client) for client in oidc_clients.values()],
        )

    @classmethod
    def _ensure_loaded(cls, *, force: bool = False):
        now = time.time()
        if not force and cls._loaded_at is not None and (now - cls._loaded_at) < cls._cache_ttl_seconds:
            return
        with cls._lock:
            # Double-check inside lock to avoid redundant reloads
            if not force and cls._loaded_at is not None and (now - cls._loaded_at) < cls._cache_ttl_seconds:
                return
            try:
                cls._load_from_db()
            except RuntimeError:
                raise
            except Exception as e:
                logger.debug(
                    "client_registry_db_load_failed_fallback_to_settings error_type=%s error=%r",
                    type(e).__name__,
                    e,
                    exc_info=True,
                )
                cls._load_from_settings()

    @classmethod
    def get_oidc_client(cls, client_id: str) -> Optional[OIDCClient]:
        cls._ensure_loaded()
        c = cls._oidc_clients.get(client_id)
        if c and c.enabled:
            return c
        return None

    @classmethod
    def validate_oidc_redirect_uri(cls, client_id: str, redirect_uri: str) -> bool:
        client = cls.get_oidc_client(client_id)
        if not client:
            return False
        return redirect_uri in client.redirect_uris

    @classmethod
    def get_idp_settings(cls) -> IdPSettings:
        cls._ensure_loaded()
        if cls._idp_settings is None:
            cls._load_from_settings()
        assert cls._idp_settings is not None
        return cls._idp_settings

    @classmethod
    def get_dingtalk_app(cls, app_id: int) -> Optional[DingTalkApp]:
        cls._ensure_loaded()
        app = cls._dingtalk_apps.get(app_id)
        if app and app.enabled:
            logger.debug("dingtalk_app_lookup app_id=%s result=enabled app=%r", app_id, _dingtalk_app_debug(app))
            return app
        logger.debug(
            "dingtalk_app_lookup app_id=%s result=%s",
            app_id,
            "disabled" if app else "missing",
        )
        return None

    @classmethod
    def get_dingtalk_app_for_oidc_client(cls, client_id: Optional[str]) -> Optional[DingTalkApp]:
        cls._ensure_loaded()
        logger.debug("dingtalk_app_select_start client_id=%s", client_id)
        if client_id:
            c = cls._oidc_clients.get(client_id)
            if not c:
                logger.debug("dingtalk_app_select client_id=%s result=missing_oidc_client", client_id)
            elif not c.enabled:
                logger.debug("dingtalk_app_select client_id=%s result=disabled_oidc_client", client_id)
            if c and c.enabled and c.dingtalk_app_id is not None:
                app = cls.get_dingtalk_app(c.dingtalk_app_id)
                if app:
                    logger.debug(
                        "dingtalk_app_select client_id=%s source=oidc_client_binding dingtalk_app_id=%s app=%r",
                        client_id,
                        c.dingtalk_app_id,
                        _dingtalk_app_debug(app),
                    )
                    return app
                logger.debug(
                    "dingtalk_app_select client_id=%s source=oidc_client_binding dingtalk_app_id=%s result=missing_or_disabled_app",
                    client_id,
                    c.dingtalk_app_id,
                )
            elif c and c.enabled:
                logger.debug("dingtalk_app_select client_id=%s source=oidc_client_binding result=no_bound_app", client_id)
        if cls._default_dingtalk_app_id is not None:
            app = cls.get_dingtalk_app(cls._default_dingtalk_app_id)
            if app:
                logger.debug(
                    "dingtalk_app_select client_id=%s source=default_app dingtalk_app_id=%s app=%r",
                    client_id,
                    cls._default_dingtalk_app_id,
                    _dingtalk_app_debug(app),
                )
                return app
        if settings.dingtalk.app_key and settings.dingtalk.app_secret:
            app = DingTalkApp(
                id=0,
                name="Default DingTalk App",
                enabled=True,
                is_default=True,
                app_key=settings.dingtalk.app_key,
                app_secret=settings.dingtalk.app_secret,
                callback_url=settings.dingtalk.callback_url,
                fetch_user_details=settings.dingtalk.fetch_user_details,
            )
            logger.debug("dingtalk_app_select client_id=%s source=settings_fallback app=%r", client_id, _dingtalk_app_debug(app))
            return app
        logger.debug("dingtalk_app_select client_id=%s result=missing_config", client_id)
        return None

    @classmethod
    def get_all_enabled_oidc_client_ids(cls) -> list[str]:
        cls._ensure_loaded()
        return [cid for cid, c in cls._oidc_clients.items() if c.enabled]

    @classmethod
    def reload(cls) -> None:
        cls._ensure_loaded(force=True)
