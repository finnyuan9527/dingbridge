from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette import status

from app.routers import admin, dingtalk, oidc
from app.services.auth_orchestrator import RequireLogin
from app.services.cache import RedisManager
from app.services.config_store import seed_defaults_if_needed


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    RedisManager.get_client()
    seed_defaults_if_needed()
    yield
    # Shutdown
    await RedisManager.close()


def create_app() -> FastAPI:
    app = FastAPI(title="dingbridge SSO", version="0.1.0", lifespan=lifespan)

    app.include_router(oidc.router)
    app.include_router(oidc.well_known_router)
    app.include_router(dingtalk.router)
    app.include_router(admin.router)

    @app.get("/healthz", tags=["meta"])
    async def healthz():
        """
        K8s Liveness/Readiness Probe Endpoint
        """
        # 简单检查 Redis 连接
        try:
            redis = RedisManager.get_client()
            await redis.ping()
            return {"status": "ok", "redis": "connected", "version": "0.1.0"}
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "error", "redis": str(e), "version": "0.1.0"},
            )

    @app.exception_handler(RequireLogin)
    async def require_login_handler(request: Request, exc: RequireLogin):
        return RedirectResponse(url=exc.redirect_to, status_code=status.HTTP_302_FOUND)

    return app


app = create_app()
