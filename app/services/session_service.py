from datetime import timedelta
from typing import Optional

from fastapi import Response

from app.config import settings
from app.models.user import User
from app.services.cache import get_redis

SESSION_TTL_MINUTES = settings.security.session_ttl_minutes
SESSION_KEY_PREFIX = "dingbridge:session:"


def _get_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


async def create_session(session_id: str, user: User) -> None:
    redis = get_redis()
    key = _get_key(session_id)
    # 使用 Redis 的 EX (expire) 参数自动处理过期
    # Pydantic v2 使用 model_dump_json
    await redis.set(
        key,
        user.model_dump_json(),
        ex=timedelta(minutes=SESSION_TTL_MINUTES)
    )


async def get_user_by_session(session_id: Optional[str]) -> Optional[User]:
    if not session_id:
        return None
    
    redis = get_redis()
    key = _get_key(session_id)
    data = await redis.get(key)
    
    if not data:
        return None
    
    # 自动续期？通常根据安全策略决定。这里暂不自动续期，保持简单。
    try:
        return User.model_validate_json(data)
    except Exception:
        return None


async def delete_session(session_id: Optional[str]) -> None:
    if not session_id:
        return
    redis = get_redis()
    key = _get_key(session_id)
    await redis.delete(key)


def set_session_cookie(response: Response, session_id: str) -> None:
    """
    统一设置会话 Cookie，确保安全属性一致。
    """
    response.set_cookie(
        key=settings.security.cookie_name,
        value=session_id,
        httponly=True,
        secure=settings.security.cookie_secure,
        samesite=settings.security.cookie_samesite,
        domain=settings.security.cookie_domain,
        max_age=SESSION_TTL_MINUTES * 60,
    )


def clear_session_cookie(response: Response) -> None:
    """
    统一清除会话 Cookie，确保属性与 set 时一致。
    """
    response.delete_cookie(
        key=settings.security.cookie_name,
        secure=settings.security.cookie_secure,
        samesite=settings.security.cookie_samesite,
        domain=settings.security.cookie_domain,
    )
