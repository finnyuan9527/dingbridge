from __future__ import annotations

import hmac
from pathlib import Path

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from pydantic import AnyHttpUrl, BaseModel
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse

from app.config import settings
from app.db import get_session
from app.db.models import DingTalkAppORM, IdPSettingsORM, OIDCClientORM
from app.services import client_registry


router = APIRouter(prefix="/admin", tags=["admin"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _require_admin_key(x_admin_key: str | None):
    """校验 Admin API Key。

    - 使用 hmac.compare_digest 做常量时间比较，防止时序攻击。
    - 统一返回同一个 403，不区分「未配置」和「密钥错误」，避免信息泄露。
    """
    configured_key = settings.security.admin_api_key
    provided_key = x_admin_key or ""
    # 两个条件都必须满足：key 已配置 且 比较结果相等
    # 注意：即使 configured_key 为空也要走 compare_digest，保证恒定时间
    key_ok = bool(configured_key) and hmac.compare_digest(
        configured_key.encode("utf-8"),
        provided_key.encode("utf-8"),
    )
    if not key_ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


class IdPSettingsUpdate(BaseModel):
    oidc_issuer: Optional[AnyHttpUrl] = None
    oidc_id_token_exp_minutes: Optional[int] = None


class IdPSettingsOut(BaseModel):
    oidc_issuer: AnyHttpUrl
    oidc_id_token_exp_minutes: int


def _get_idp_settings_sync():
    s = client_registry.ClientRegistry.get_idp_settings()
    return IdPSettingsOut(
        oidc_issuer=s.oidc_issuer,
        oidc_id_token_exp_minutes=s.oidc_id_token_exp_minutes,
    )


@router.get("/idp-settings", response_model=IdPSettingsOut)
async def get_idp_settings(x_admin_key: str | None = Header(default=None)):
    _require_admin_key(x_admin_key)
    return await run_in_threadpool(_get_idp_settings_sync)


def _update_idp_settings_sync(payload: IdPSettingsUpdate):
    with get_session() as db:
        row = db.get(IdPSettingsORM, 1)
        if row is None:
            row = IdPSettingsORM(
                id=1,
                oidc_issuer=str(settings.oidc.issuer),
                oidc_id_token_exp_minutes=settings.oidc.id_token_exp_minutes,
            )
            db.add(row)
            db.flush()

        if payload.oidc_issuer is not None:
            row.oidc_issuer = str(payload.oidc_issuer)
        if payload.oidc_id_token_exp_minutes is not None:
            row.oidc_id_token_exp_minutes = int(payload.oidc_id_token_exp_minutes)

    client_registry.ClientRegistry.reload()
    s = client_registry.ClientRegistry.get_idp_settings()
    return IdPSettingsOut(
        oidc_issuer=s.oidc_issuer,
        oidc_id_token_exp_minutes=s.oidc_id_token_exp_minutes,
    )


@router.put("/idp-settings", response_model=IdPSettingsOut)
async def update_idp_settings(payload: IdPSettingsUpdate, x_admin_key: str | None = Header(default=None)):
    _require_admin_key(x_admin_key)
    return await run_in_threadpool(_update_idp_settings_sync, payload)


class DingTalkAppUpsert(BaseModel):
    id: Optional[int] = None
    name: str = ""
    enabled: bool = True
    is_default: bool = False
    app_key: str
    app_secret: Optional[str] = None
    callback_url: AnyHttpUrl
    fetch_user_details: bool = True


class DingTalkAppOut(BaseModel):
    id: int
    name: str
    enabled: bool
    is_default: bool
    app_key: str
    callback_url: AnyHttpUrl
    fetch_user_details: bool


def _list_dingtalk_apps_sync():
    with get_session() as db:
        rows = db.execute(select(DingTalkAppORM)).scalars().all()
        return [
            DingTalkAppOut(
                id=r.id,
                name=r.name,
                enabled=r.enabled,
                is_default=r.is_default,
                app_key=r.app_key,
                callback_url=r.callback_url,
                fetch_user_details=r.fetch_user_details,
            )
            for r in rows
        ]


@router.get("/dingtalk-apps", response_model=list[DingTalkAppOut])
async def list_dingtalk_apps(x_admin_key: str | None = Header(default=None)):
    _require_admin_key(x_admin_key)
    return await run_in_threadpool(_list_dingtalk_apps_sync)


def _upsert_dingtalk_app_sync(payload: DingTalkAppUpsert):
    with get_session() as db:
        row = db.get(DingTalkAppORM, payload.id) if payload.id else None
        if row is None:
            if payload.app_secret is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing_app_secret")
            row = DingTalkAppORM(
                name=payload.name,
                enabled=payload.enabled,
                is_default=payload.is_default,
                app_key=payload.app_key,
                app_secret=payload.app_secret,
                callback_url=str(payload.callback_url),
                fetch_user_details=payload.fetch_user_details,
            )
            db.add(row)
            db.flush()
        else:
            row.name = payload.name
            row.enabled = payload.enabled
            row.is_default = payload.is_default
            row.app_key = payload.app_key
            row.callback_url = str(payload.callback_url)
            row.fetch_user_details = payload.fetch_user_details
            if payload.app_secret is not None:
                row.app_secret = payload.app_secret

    client_registry.ClientRegistry.reload()
    return DingTalkAppOut(
        id=row.id,
        name=row.name,
        enabled=row.enabled,
        is_default=row.is_default,
        app_key=row.app_key,
        callback_url=row.callback_url,
        fetch_user_details=row.fetch_user_details,
    )


@router.post("/dingtalk-apps", response_model=DingTalkAppOut)
async def upsert_dingtalk_app(payload: DingTalkAppUpsert, x_admin_key: str | None = Header(default=None)):
    _require_admin_key(x_admin_key)
    return await run_in_threadpool(_upsert_dingtalk_app_sync, payload)


class OIDCClientUpsert(BaseModel):
    client_id: str
    name: str = ""
    enabled: bool = True
    client_secret: Optional[str] = None
    redirect_uris: list[AnyHttpUrl]
    dingtalk_app_id: Optional[int] = None


class OIDCClientOut(BaseModel):
    client_id: str
    name: str
    enabled: bool
    redirect_uris: list[AnyHttpUrl]
    dingtalk_app_id: Optional[int] = None


def _list_oidc_clients_sync():
    with get_session() as db:
        rows = db.execute(select(OIDCClientORM)).scalars().all()
        return [
            OIDCClientOut(
                client_id=r.client_id,
                name=r.name,
                enabled=r.enabled,
                redirect_uris=[u for u in (r.redirect_uris or [])],
                dingtalk_app_id=r.dingtalk_app_id,
            )
            for r in rows
        ]


@router.get("/oidc-clients", response_model=list[OIDCClientOut])
async def list_oidc_clients(x_admin_key: str | None = Header(default=None)):
    _require_admin_key(x_admin_key)
    return await run_in_threadpool(_list_oidc_clients_sync)


def _upsert_oidc_client_sync(payload: OIDCClientUpsert):
    with get_session() as db:
        row = db.get(OIDCClientORM, payload.client_id)
        if row is None:
            if payload.client_secret is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing_client_secret")
            row = OIDCClientORM(
                client_id=payload.client_id,
                name=payload.name,
                enabled=payload.enabled,
                client_secret=payload.client_secret,
                redirect_uris=[str(u) for u in payload.redirect_uris],
                dingtalk_app_id=payload.dingtalk_app_id,
            )
            db.add(row)
        else:
            row.name = payload.name
            row.enabled = payload.enabled
            row.redirect_uris = [str(u) for u in payload.redirect_uris]
            row.dingtalk_app_id = payload.dingtalk_app_id
            if payload.client_secret is not None:
                row.client_secret = payload.client_secret

    client_registry.ClientRegistry.reload()
    return OIDCClientOut(
        client_id=row.client_id,
        name=row.name,
        enabled=row.enabled,
        redirect_uris=[u for u in (row.redirect_uris or [])],
        dingtalk_app_id=row.dingtalk_app_id,
    )


@router.post("/oidc-clients", response_model=OIDCClientOut)
async def upsert_oidc_client(payload: OIDCClientUpsert, x_admin_key: str | None = Header(default=None)):
    _require_admin_key(x_admin_key)
    return await run_in_threadpool(_upsert_oidc_client_sync, payload)


def _reload_sync():
    client_registry.ClientRegistry.reload()
    return {"ok": True}


@router.post("/reload", response_model=Dict[str, Any])
async def reload_runtime_config(x_admin_key: str | None = Header(default=None)):
    _require_admin_key(x_admin_key)
    return await run_in_threadpool(_reload_sync)


@router.get("/console/oidc-clients", response_class=HTMLResponse)
async def oidc_client_console(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin/oidc_clients.html",
        context={
            "request": request,
            "page_title": "OIDC Client Console",
            "oidc_clients_endpoint": "/admin/oidc-clients",
            "dingtalk_apps_endpoint": "/admin/dingtalk-apps",
            "oidc_console_css": "/static/admin/oidc_clients.css",
            "oidc_console_js": "/static/admin/oidc_clients.js",
        },
    )
