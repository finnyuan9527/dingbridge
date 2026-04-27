from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from pydantic import AnyHttpUrl, BaseModel
from sqlalchemy import select

from app.config import settings
from app.db import create_all, get_session
from app.db.models import DingTalkAppORM, IdPSettingsORM, OIDCClientORM


class IdPSettings(BaseModel):
    oidc_issuer: AnyHttpUrl
    oidc_id_token_exp_minutes: int


class DingTalkApp(BaseModel):
    id: int
    name: str = ""
    enabled: bool = True
    is_default: bool = False
    app_key: str
    app_secret: str
    callback_url: AnyHttpUrl
    fetch_user_details: bool = True


def seed_defaults_if_needed() -> None:
    create_all()
    with get_session() as db:
        idp = db.get(IdPSettingsORM, 1)
        if idp is None:
            idp = IdPSettingsORM(
                id=1,
                oidc_issuer=str(settings.oidc.issuer),
                oidc_id_token_exp_minutes=settings.oidc.id_token_exp_minutes,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(idp)

        existing_default_app = (
            db.execute(select(DingTalkAppORM).where(DingTalkAppORM.is_default.is_(True))).scalars().first()
        )
        if existing_default_app is None and settings.dingtalk.app_key and settings.dingtalk.app_secret:
            app = DingTalkAppORM(
                name="Default DingTalk App",
                enabled=True,
                is_default=True,
                app_key=settings.dingtalk.app_key,
                app_secret=settings.dingtalk.app_secret,
                callback_url=str(settings.dingtalk.callback_url),
                fetch_user_details=settings.dingtalk.fetch_user_details,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(app)
            db.flush()
            default_app_id = app.id
        else:
            default_app_id = existing_default_app.id if existing_default_app else None

        existing_oidc = db.execute(select(OIDCClientORM).limit(1)).scalars().first()
        if existing_oidc is None and settings.oidc.client_id and settings.oidc.client_secret:
            db.add(
                OIDCClientORM(
                    client_id=settings.oidc.client_id,
                    client_secret=settings.oidc.client_secret,
                    redirect_uris=[str(settings.oidc.redirect_uri)],
                    name="Default OIDC Client",
                    enabled=True,
                    dingtalk_app_id=default_app_id,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )


def load_idp_settings() -> IdPSettings:
    with get_session() as db:
        row = db.get(IdPSettingsORM, 1)
        if row is None:
            return IdPSettings(
                oidc_issuer=settings.oidc.issuer,
                oidc_id_token_exp_minutes=settings.oidc.id_token_exp_minutes,
            )
        return IdPSettings(
            oidc_issuer=row.oidc_issuer,
            oidc_id_token_exp_minutes=row.oidc_id_token_exp_minutes,
        )


def load_dingtalk_apps() -> Dict[int, DingTalkApp]:
    with get_session() as db:
        apps = db.execute(select(DingTalkAppORM)).scalars().all()
        out: Dict[int, DingTalkApp] = {}
        for a in apps:
            out[a.id] = DingTalkApp(
                id=a.id,
                name=a.name,
                enabled=a.enabled,
                is_default=a.is_default,
                app_key=a.app_key,
                app_secret=a.app_secret,
                callback_url=a.callback_url,
                fetch_user_details=a.fetch_user_details,
            )
        return out


def get_default_dingtalk_app_id(apps: Dict[int, DingTalkApp]) -> Optional[int]:
    for a in apps.values():
        if a.enabled and a.is_default:
            return a.id
    return None


def load_oidc_clients() -> Dict[str, dict]:
    with get_session() as db:
        rows = db.execute(select(OIDCClientORM)).scalars().all()
        out: Dict[str, dict] = {}
        for r in rows:
            out[r.client_id] = {
                "client_id": r.client_id,
                "client_secret": r.client_secret,
                "redirect_uris": list(r.redirect_uris or []),
                "name": r.name,
                "enabled": r.enabled,
                "dingtalk_app_id": r.dingtalk_app_id,
            }
        return out
