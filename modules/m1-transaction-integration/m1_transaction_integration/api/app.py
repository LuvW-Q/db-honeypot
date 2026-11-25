"""FastAPI 应用入口。

- 挂载控制台只读接口与少量配置接口
- 健康检查包含数据库与诱饵服务状态
- 生产模式可托管前端构建产物
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from m1_transaction_integration.api.errors import register_exception_handlers
from shared.config import REPO_ROOT, settings
from shared.db.session import ping
from shared.logging import configure_logging, get_logger
from shared.schemas.common import HealthResponse, iso_utc, utc_now

configure_logging()
logger = get_logger("api.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动/关闭日志。"""
    logger.info("API 启动", host=settings.api_host, port=settings.api_port)
    yield
    logger.info("API 关闭")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(
        title="数据库蜜罐与攻击行为分析系统 API",
        description="课程项目：诱饵事件、会话时间线、攻击者画像与告警的只读查询接口",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "PATCH", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        """为每个请求生成/透传 request_id，并在响应头返回。"""
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/api/health", response_model=HealthResponse, tags=["health"])
    async def health(request: Request):
        """健康检查：数据库连通性、诱饵服务状态与版本（对齐契约 3.1）。"""
        started = time.perf_counter()
        db_ok = await ping()
        latency_ms = int((time.perf_counter() - started) * 1000) if db_ok else None
        honeypot_ok = await _probe_tcp(settings.honeypot_host, settings.honeypot_port)
        request_id = getattr(request.state, "request_id", None)
        payload = {
            "status": "ok" if db_ok else "degraded",
            "version": "0.1.0",
            "database": {"status": "ok" if db_ok else "down", "latency_ms": latency_ms},
            "honeypot": {
                "status": "ok" if honeypot_ok else "down",
                "listen": f"{settings.honeypot_host}:{settings.honeypot_port}",
                "accepted_connections": 0,
            },
            "generated_at": iso_utc(utc_now()),
        }
        if db_ok:
            return JSONResponse(status_code=200, content=payload)
        payload.update(
            {
                "code": "DB_UNAVAILABLE",
                "message": "数据库连接不可用",
                "detail": {"stage": "connect"},
                "request_id": request_id,
            }
        )
        return JSONResponse(status_code=503, content=payload)

    _register_routers(app)
    _mount_frontend(app)
    return app


async def _probe_tcp(host: str, port: int, timeout: float = 0.3) -> bool:
    """探测诱饵服务端口是否可连接（不参与业务判断）。"""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:  # noqa: BLE001
        return False


def _register_routers(app: FastAPI) -> None:
    """注册各业务路由；模块缺失时允许应用先以健康检查启动。"""
    try:
        from m1_transaction_integration.api.routes import (
            alerts,
            attackers,
            overview,
            rules,
            sessions,
        )
    except ImportError:  # pragma: no cover - 渐进式集成阶段
        logger.warning("业务路由尚未就绪，仅提供健康检查")
        return

    app.include_router(overview.router, prefix="/api", tags=["overview"])
    app.include_router(attackers.router, prefix="/api", tags=["attackers"])
    app.include_router(sessions.router, prefix="/api", tags=["sessions"])
    app.include_router(alerts.router, prefix="/api", tags=["alerts"])
    app.include_router(rules.router, prefix="/api", tags=["rules"])
    try:
        from m1_transaction_integration.api.routes import ai
    except ImportError:
        pass
    else:
        app.include_router(ai.router, prefix="/api", tags=["ai"])


def _mount_frontend(app: FastAPI) -> None:
    """若前端已构建，托管静态产物（SPA 由前端路由处理）。"""
    dist = Path(settings.web_dist_dir)
    if not dist.is_absolute():
        dist = (REPO_ROOT / dist).resolve()
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")
        logger.info("前端静态资源已挂载", dist=str(dist))
    else:
        logger.info("未发现前端构建产物，跳过静态托管", dist=str(dist))


app = create_app()
