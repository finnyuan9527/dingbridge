import logging
from typing import Optional

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

