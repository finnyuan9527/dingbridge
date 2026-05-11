import base64
import binascii
import hashlib
from typing import Any, Dict, Optional

from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from jose.exceptions import JWTError
from jose import jwt as jose_jwt

from app.config import settings
from app.services import auth_orchestrator, oidc_store, token_service, client_registry, session_service
from app.security import audit


router = APIRouter(prefix="/oidc", tags=["oidc"])
well_known_router = APIRouter(tags=["oidc"])


def _openid_configuration() -> Dict[str, Any]:
    issuer = str(client_registry.ClientRegistry.get_idp_settings().oidc_issuer).rstrip("/")
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oidc/authorize",
        "token_endpoint": f"{issuer}/oidc/token",
        "userinfo_endpoint": f"{issuer}/oidc/userinfo",
        "jwks_uri": f"{issuer}/oidc/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "scopes_supported": ["openid", "profile", "email", "phone", "groups"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": [settings.security.jwt_algorithm],
    }

@well_known_router.get("/.well-known/openid-configuration", include_in_schema=False)
async def openid_configuration_root() -> Dict[str, Any]:
    return _openid_configuration()


@router.get("/.well-known/openid-configuration", include_in_schema=False)
async def openid_configuration_prefixed() -> Dict[str, Any]:
    return _openid_configuration()


@router.get("/jwks.json", include_in_schema=False)
async def jwks() -> Dict[str, Any]:
    return token_service.get_jwks()


@router.get("/authorize")
async def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: Optional[str] = None,
    nonce: Optional[str] = None,
    response_mode: Optional[str] = None,
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = None,
) -> Response:
    if "openid" not in (scope or "").split():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_scope")
    if response_type != "code":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_response_type")
    if code_challenge and code_challenge_method != "S256":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_code_challenge_method")
    if code_challenge_method and not code_challenge:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request")

    # 校验 ClientID 和 RedirectURI
    client = client_registry.ClientRegistry.get_oidc_client(client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_client")
    
    if redirect_uri not in client.redirect_uris:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_redirect_uri")
    if client.require_pkce and not code_challenge:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request")

    user = await auth_orchestrator.ensure_user_session_via_dingtalk(request, client_id=client_id)

    params: Dict[str, str] = {}
    code = await oidc_store.issue_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        user=user,
        nonce=nonce,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )
    params["code"] = code

    if state is not None:
        params["state"] = state

    redirect_url = oidc_store.build_redirect_uri_with_params(redirect_uri, params, fragment=False)

    ip = request.client.host if request.client else None
    await audit.log_login_success_async(
        user=user,
        source="oidc_authorize",
        client_id=client_id,
        ip=ip,
    )

    resp = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    return resp


@router.post("/token")
async def token(
    request: Request,
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
) -> JSONResponse:
    if grant_type not in ("authorization_code", "refresh_token"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_grant_type")

    basic = request.headers.get("authorization")
    if basic and basic.lower().startswith("basic "):
        try:
            raw = base64.b64decode(basic.split(" ", 1)[1]).decode("utf-8")
            cid, csec = raw.split(":", 1)
        except (binascii.Error, UnicodeDecodeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_client")
        client_id = client_id or cid
        client_secret = client_secret or csec

    if not client_id or not client_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_client_credentials")

    client = client_registry.ClientRegistry.get_oidc_client(client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_client")
    
    if client.client_secret != client_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_client_secret")

    user = None
    scope = ""
    nonce: Optional[str] = None
    next_refresh_token: Optional[str] = None

    if grant_type == "authorization_code":
        if not code or not redirect_uri:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request")

        code_data = await oidc_store.consume_code(code)
        if not code_data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")
        if code_data.client_id != client_id or code_data.redirect_uri != redirect_uri:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")

        if code_data.code_challenge:
            if not code_verifier:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request")
            if code_data.code_challenge_method != "S256":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")
            digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
            computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            if computed != code_data.code_challenge:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")

        user = code_data.user
        scope = code_data.scope
        nonce = code_data.nonce
        next_refresh_token = await oidc_store.issue_refresh_token(
            client_id=client_id,
            scope=scope,
            user=user,
        )
    else:
        if not refresh_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request")

        refresh_data = await oidc_store.consume_refresh_token(refresh_token)
        if not refresh_data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")
        if refresh_data.client_id != client_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")

        user = refresh_data.user
        scope = refresh_data.scope
        next_refresh_token = await oidc_store.issue_refresh_token(
            client_id=client_id,
            scope=scope,
            user=user,
        )

    assert user is not None
    access_token = token_service.create_access_token(user, client_id=client_id, scope=scope)
    id_token = token_service.create_id_token(user, client_id=client_id, nonce=nonce)

    ip = request.client.host if request.client else None
    await audit.log_token_issued_async(
        user=user,
        client_id=client_id,
        scope=scope,
        ip=ip,
    )

    payload: Dict[str, Any] = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": client_registry.ClientRegistry.get_idp_settings().oidc_access_token_exp_minutes * 60,
        "id_token": id_token,
        "scope": scope,
    }
    if next_refresh_token is not None:
        payload["refresh_token"] = next_refresh_token

    return JSONResponse(payload)


@router.get("/userinfo")
async def userinfo(request: Request) -> Dict[str, Any]:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_bearer_token")
    token = auth.split(" ", 1)[1].strip()

    audiences = client_registry.ClientRegistry.get_all_enabled_oidc_client_ids()
    try:
        claims = token_service.decode_and_verify_bearer(token, audience=audiences)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")
    scope = str(claims.get("scope") or "")
    scopes = set(scope.split())

    out: Dict[str, Any] = {"sub": claims["sub"]}
    if "profile" in scopes:
        if claims.get("name") is not None:
            out["name"] = claims.get("name")
    if "email" in scopes:
        if claims.get("email") is not None:
            out["email"] = claims.get("email")
    if "phone" in scopes:
        if claims.get("phone_number") is not None:
            out["phone_number"] = claims.get("phone_number")
    if "groups" in scopes and claims.get("groups") is not None:
        out["groups"] = claims.get("groups")
    return out


def _validate_post_logout_redirect_uri(
    *,
    client_id: Optional[str],
    post_logout_redirect_uri: Optional[str],
) -> Optional[str]:
    if not post_logout_redirect_uri:
        return None
    if not client_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_post_logout_redirect_uri")
    client = client_registry.ClientRegistry.get_oidc_client(client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_client")
    if post_logout_redirect_uri not in client.redirect_uris:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_post_logout_redirect_uri")
    return post_logout_redirect_uri


def _resolve_client_id_for_logout(
    *,
    client_id: Optional[str],
    id_token_hint: Optional[str],
) -> Optional[str]:
    """
    支持从 id_token_hint 推导 client_id（aud）。
    若同时传入 client_id，则要求二者一致。
    """
    if not id_token_hint:
        return client_id

    try:
        claims = jose_jwt.get_unverified_claims(id_token_hint)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_id_token_hint")

    aud_claim = claims.get("aud")
    aud_values = aud_claim if isinstance(aud_claim, list) else [aud_claim]
    aud_values = [a for a in aud_values if isinstance(a, str) and a]
    if not aud_values:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_id_token_hint")
    hinted_client_id = aud_values[0]

    if client_id and client_id != hinted_client_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_client")
    return hinted_client_id


@router.post("/logout")
async def logout(
    request: Request,
    refresh_token: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    post_logout_redirect_uri: Optional[str] = Form(None),
    id_token_hint: Optional[str] = Form(None),
    state: Optional[str] = Form(None),
) -> JSONResponse:
    session_id = request.cookies.get(settings.security.cookie_name)
    await session_service.delete_session(session_id)

    if refresh_token:
        await oidc_store.revoke_refresh_token(refresh_token)

    resolved_client_id = _resolve_client_id_for_logout(client_id=client_id, id_token_hint=id_token_hint)
    redirect_uri = _validate_post_logout_redirect_uri(
        client_id=resolved_client_id,
        post_logout_redirect_uri=post_logout_redirect_uri,
    )
    if redirect_uri:
        url = oidc_store.build_redirect_uri_with_params(
            redirect_uri,
            {"state": state} if state is not None else {},
            fragment=False,
        )
        resp = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
        session_service.clear_session_cookie(resp)
        return resp

    payload: Dict[str, Any] = {"ok": True}
    if state is not None:
        payload["state"] = state
    resp = JSONResponse(payload)
    session_service.clear_session_cookie(resp)
    return resp


@router.get("/logout")
async def logout_get(
    request: Request,
    refresh_token: Optional[str] = None,
    client_id: Optional[str] = None,
    post_logout_redirect_uri: Optional[str] = None,
    id_token_hint: Optional[str] = None,
    state: Optional[str] = None,
) -> RedirectResponse:
    session_id = request.cookies.get(settings.security.cookie_name)
    await session_service.delete_session(session_id)

    if refresh_token:
        await oidc_store.revoke_refresh_token(refresh_token)

    resolved_client_id = _resolve_client_id_for_logout(client_id=client_id, id_token_hint=id_token_hint)
    redirect_uri = _validate_post_logout_redirect_uri(
        client_id=resolved_client_id,
        post_logout_redirect_uri=post_logout_redirect_uri,
    ) or "/"
    url = oidc_store.build_redirect_uri_with_params(
        redirect_uri,
        {"state": state} if state is not None else {},
        fragment=False,
    )
    resp = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    session_service.clear_session_cookie(resp)
    return resp
