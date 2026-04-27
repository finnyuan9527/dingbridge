from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import os
import threading

from jose import jwt

from app.config import settings
from app.models.user import User
from app.services import client_registry
from app.services.identity_mapping import user_to_oidc_claims


_KID = "dingbridge-rsa-1"

# --- Lazy key loading ---
# Avoids module-level side effects that prevent importing before env is configured
# (e.g. in tests) and make error handling impossible for callers.

_PRIVATE_KEY_PEM: Optional[str] = None
_PUBLIC_KEY_PEM: Optional[str] = None
_keys_lock = threading.Lock()


def _load_signing_keys() -> tuple[str, str]:
    """
    返回 (private_pem, public_pem)。

    - 优先尝试从 jwt_private_key_path 指定的文件加载
    - 其次尝试从 settings.jwt_private_key 环境变量加载
    - 默认不允许生成进程内临时 RSA 密钥对（会导致多实例/重启后验签不稳定）
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_raw = ""
    # 1. 优先从文件路径加载
    if settings.security.jwt_private_key_path:
        try:
            with open(settings.security.jwt_private_key_path, "r", encoding="utf-8") as f:
                private_raw = f.read()
        except FileNotFoundError:
            # 如果配置了路径但文件不存在，抛错还是降级？
            # 生产环境应该抛错
            pass
    
    # 2. 其次从环境变量加载
    if not private_raw and settings.security.jwt_private_key:
        private_raw = settings.security.jwt_private_key.replace("\\n", "\n")

    if not private_raw:
        if settings.security.allow_ephemeral_keys:
            priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            priv_pem = priv.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode("utf-8")
            pub_pem = priv.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")
            return priv_pem, pub_pem
        raise RuntimeError("missing SECURITY__JWT_PRIVATE_KEY or SECURITY__JWT_PRIVATE_KEY_PATH")

    private_pem = private_raw.encode("utf-8")

    try:
        priv = serialization.load_pem_private_key(private_pem, password=None)
        
        public_raw = ""
        # 尝试加载公钥，优先文件，其次环境变量
        if settings.security.jwt_public_key_path:
             try:
                with open(settings.security.jwt_public_key_path, "r", encoding="utf-8") as f:
                    public_raw = f.read()
             except FileNotFoundError:
                 pass
        
        if not public_raw and settings.security.jwt_public_key:
            public_raw = settings.security.jwt_public_key.replace("\\n", "\n")

        if public_raw:
            public_pem = public_raw
        else:
            pub = priv.public_key()
            public_pem = pub.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")
        return (private_pem.decode("utf-8"), public_pem)
    except Exception:
        if settings.security.allow_ephemeral_keys:
            priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            priv_pem = priv.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode("utf-8")
            pub_pem = priv.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")
            return priv_pem, pub_pem
        raise RuntimeError("invalid SECURITY__JWT_PRIVATE_KEY")


def _get_keys() -> tuple[str, str]:
    """
    延迟加载并缓存密钥对。线程安全。
    """
    global _PRIVATE_KEY_PEM, _PUBLIC_KEY_PEM
    if _PRIVATE_KEY_PEM is not None and _PUBLIC_KEY_PEM is not None:
        return _PRIVATE_KEY_PEM, _PUBLIC_KEY_PEM
    with _keys_lock:
        if _PRIVATE_KEY_PEM is not None and _PUBLIC_KEY_PEM is not None:
            return _PRIVATE_KEY_PEM, _PUBLIC_KEY_PEM
        _PRIVATE_KEY_PEM, _PUBLIC_KEY_PEM = _load_signing_keys()
        return _PRIVATE_KEY_PEM, _PUBLIC_KEY_PEM


def _issuer() -> str:
    return str(client_registry.ClientRegistry.get_idp_settings().oidc_issuer).rstrip("/")


def create_id_token(user: User, *, client_id: str, nonce: Optional[str] = None) -> str:
    private_key, _ = _get_keys()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=client_registry.ClientRegistry.get_idp_settings().oidc_id_token_exp_minutes)

    payload: Dict[str, Any] = {
        "iss": _issuer(),
        "sub": user.subject,
        "aud": client_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }

    # 使用统一的 OIDC Claims 映射，并在 ID Token 中默认不包含 phone_number，
    # 以保持与现有实现兼容。
    extra_claims = user_to_oidc_claims(user)
    extra_claims.pop("phone_number", None)
    payload.update(extra_claims)
    if nonce:
        payload["nonce"] = nonce

    token = jwt.encode(
        payload,
        private_key,
        algorithm=settings.security.jwt_algorithm,
        headers={"kid": _KID},
    )
    return token


def create_access_token(user: User, *, client_id: str, scope: str) -> str:
    private_key, _ = _get_keys()
    now = datetime.now(timezone.utc)
    idp = client_registry.ClientRegistry.get_idp_settings()
    exp = now + timedelta(minutes=idp.oidc_access_token_exp_minutes)

    payload: Dict[str, Any] = {
        "iss": _issuer(),
        "sub": user.subject,
        "aud": client_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "scope": scope,
    }

    # Access Token 直接复用统一的 OIDC Claims 映射。
    payload.update(user_to_oidc_claims(user))
    token = jwt.encode(
        payload,
        private_key,
        algorithm=settings.security.jwt_algorithm,
        headers={"kid": _KID},
    )
    return token


def get_jwks() -> Dict[str, Any]:
    """
    从 PEM 公钥生成 JWKS。

    生产环境务必通过环境变量注入真实密钥，否则将无法启动。
    """
    from base64 import urlsafe_b64encode

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    _, public_key_pem = _get_keys()

    def _b64u_uint(val: int) -> str:
        raw = val.to_bytes((val.bit_length() + 7) // 8, "big")
        return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    key = None
    try:
        key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    except Exception:
        key = None

    if not isinstance(key, rsa.RSAPublicKey):
        # Keep output shape stable; downstream will fail validation if not RSA anyway.
        return {"keys": []}

    numbers = key.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": settings.security.jwt_algorithm,
                "kid": _KID,
                "n": _b64u_uint(numbers.n),
                "e": _b64u_uint(numbers.e),
            }
        ]
    }


def decode_and_verify_bearer(token: str, *, audience: str | list[str]) -> Dict[str, Any]:
    _, public_key_pem = _get_keys()
    return jwt.decode(
        token,
        public_key_pem,
        algorithms=[settings.security.jwt_algorithm],
        issuer=_issuer(),
        audience=audience,
        options={"verify_at_hash": False},
    )
