import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from urllib.parse import quote

from pydantic import BaseModel

from app.config import settings
from app.models.user import User
from app.services.cache import get_redis


class AuthorizationCode(BaseModel):
    code: str
    client_id: str
    redirect_uri: str
    scope: str
    user: User
    nonce: Optional[str] = None
    code_challenge: Optional[str] = None
    code_challenge_method: Optional[str] = None
    expires_at: datetime


class RefreshToken(BaseModel):
    refresh_token: str
    client_id: str
    scope: str
    user: User
    issued_at: datetime
    expires_at: datetime


AUTH_CODE_TTL_SECONDS = 60
CODE_KEY_PREFIX = "dingbridge:code:"
REFRESH_TOKEN_KEY_PREFIX = "dingbridge:refresh:"


def _get_key(code: str) -> str:
    return f"{CODE_KEY_PREFIX}{code}"


def _get_refresh_key(refresh_token: str) -> str:
    return f"{REFRESH_TOKEN_KEY_PREFIX}{refresh_token}"


async def issue_code(
    *,
    client_id: str,
    redirect_uri: str,
    scope: str,
    user: User,
    nonce: Optional[str],
    code_challenge: Optional[str],
    code_challenge_method: Optional[str],
) -> str:
    code = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=AUTH_CODE_TTL_SECONDS)
    
    auth_code = AuthorizationCode(
        code=code,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        user=user,
        nonce=nonce,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        expires_at=expires_at,
    )

    redis = get_redis()
    key = _get_key(code)
    await redis.set(
        key,
        auth_code.model_dump_json(),
        ex=timedelta(seconds=AUTH_CODE_TTL_SECONDS)
    )
    return code


async def issue_refresh_token(*, client_id: str, scope: str, user: User) -> str:
    refresh_token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.oidc.refresh_token_exp_minutes)

    data = RefreshToken(
        refresh_token=refresh_token,
        client_id=client_id,
        scope=scope,
        user=user,
        issued_at=now,
        expires_at=expires_at,
    )

    redis = get_redis()
    key = _get_refresh_key(refresh_token)
    await redis.set(
        key,
        data.model_dump_json(),
        ex=timedelta(minutes=settings.oidc.refresh_token_exp_minutes),
    )
    return refresh_token


async def consume_code(code: str) -> Optional[AuthorizationCode]:
    redis = get_redis()
    key = _get_key(code)

    script = """
    local v = redis.call('GET', KEYS[1])
    if v then
      redis.call('DEL', KEYS[1])
    end
    return v
    """
    data = await redis.eval(script, 1, key)
    if not data:
        return None
    
    try:
        auth_code = AuthorizationCode.model_validate_json(data)
        if auth_code.expires_at < datetime.now(timezone.utc):
            return None
        return auth_code
    except Exception:
        return None


async def consume_refresh_token(refresh_token: str) -> Optional[RefreshToken]:
    redis = get_redis()
    key = _get_refresh_key(refresh_token)

    script = """
    local v = redis.call('GET', KEYS[1])
    if v then
      redis.call('DEL', KEYS[1])
    end
    return v
    """
    data = await redis.eval(script, 1, key)
    if not data:
        return None

    try:
        rt = RefreshToken.model_validate_json(data)
        if rt.expires_at < datetime.now(timezone.utc):
            return None
        return rt
    except Exception:
        return None


async def revoke_refresh_token(refresh_token: str) -> None:
    redis = get_redis()
    await redis.delete(_get_refresh_key(refresh_token))


def build_redirect_uri_with_params(base: str, params: Dict[str, str], *, fragment: bool) -> str:
    if not params:
        return base
    joined = "&".join(f"{quote(k)}={quote(v)}" for k, v in params.items())
    sep = "#" if fragment else ("&" if ("?" in base) else "?")
    return f"{base}{sep}{joined}"
