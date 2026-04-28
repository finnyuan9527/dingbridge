import logging
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.db.models import AuditLogORM
from app.models.user import User


_logger = logging.getLogger("dingbridge.audit")


def _safe_user_repr(user: User) -> dict:
    """
    仅记录必要的用户标识，避免泄露敏感字段。
    """
    return {
        "sub": user.subject,
        "name": user.name,
        "email": user.email,
        "groups": user.groups,
    }


def _persist_event(
    *,
    event: str,
    level: str,
    source: Optional[str],
    client_id: Optional[str],
    ip: Optional[str],
    user: Optional[User] = None,
    reason: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    user_groups = list(user.groups) if user else []
    try:
        with get_session() as db:
            db.add(
                AuditLogORM(
                    event=event,
                    level=level,
                    source=source,
                    client_id=client_id,
                    ip=ip,
                    user_sub=user.subject if user else None,
                    user_name=user.name if user else None,
                    user_email=user.email if user else None,
                    user_groups=user_groups,
                    reason=reason,
                    details=details or {},
                )
            )
    except Exception:
        # 审计落库失败不应阻断主认证链路，但要留下告警。
        _logger.exception("audit_persist_failed", extra={"event": event})


def log_login_success(
    *,
    user: User,
    source: str,
    client_id: Optional[str],
    ip: Optional[str],
) -> None:
    _logger.info(
        "login_success",
        extra={
            "event": "login_success",
            "source": source,
            "client_id": client_id,
            "ip": ip,
            "user": _safe_user_repr(user),
        },
    )
    _persist_event(
        event="login_success",
        level="info",
        source=source,
        client_id=client_id,
        ip=ip,
        user=user,
    )


async def log_login_success_async(
    *,
    user: User,
    source: str,
    client_id: Optional[str],
    ip: Optional[str],
) -> None:
    await run_in_threadpool(
        log_login_success,
        user=user,
        source=source,
        client_id=client_id,
        ip=ip,
    )


def log_login_failure(
    *,
    reason: str,
    source: str,
    client_id: Optional[str],
    ip: Optional[str],
) -> None:
    _logger.warning(
        "login_failure",
        extra={
            "event": "login_failure",
            "source": source,
            "client_id": client_id,
            "ip": ip,
            "reason": reason,
        },
    )
    _persist_event(
        event="login_failure",
        level="warning",
        source=source,
        client_id=client_id,
        ip=ip,
        reason=reason,
    )


async def log_login_failure_async(
    *,
    reason: str,
    source: str,
    client_id: Optional[str],
    ip: Optional[str],
) -> None:
    await run_in_threadpool(
        log_login_failure,
        reason=reason,
        source=source,
        client_id=client_id,
        ip=ip,
    )


def log_token_issued(
    *,
    user: User,
    client_id: str,
    scope: str,
    ip: Optional[str],
) -> None:
    _logger.info(
        "token_issued",
        extra={
            "event": "token_issued",
            "client_id": client_id,
            "ip": ip,
            "scope": scope,
            "user": _safe_user_repr(user),
        },
    )
    _persist_event(
        event="token_issued",
        level="info",
        source="oidc_token",
        client_id=client_id,
        ip=ip,
        user=user,
        details={"scope": scope},
    )


async def log_token_issued_async(
    *,
    user: User,
    client_id: str,
    scope: str,
    ip: Optional[str],
) -> None:
    await run_in_threadpool(
        log_token_issued,
        user=user,
        client_id=client_id,
        scope=scope,
        ip=ip,
    )
