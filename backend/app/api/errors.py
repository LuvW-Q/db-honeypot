"""统一异常处理：把应用异常转换为 contracts/api.md 约定的错误结构。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging import get_logger

logger = get_logger("api.errors")

# 业务错误码到 HTTP 状态的映射
STATUS_BY_CODE = {
    "NOT_FOUND": 404,
    "VALIDATION_ERROR": 422,
    "CONFLICT": 409,
    "FORBIDDEN": 403,
    "UNAUTHORIZED": 401,
    "BAD_REQUEST": 400,
    "SERVICE_UNAVAILABLE": 503,
    "INTERNAL_ERROR": 500,
}


class ApiError(Exception):
    """业务异常：携带机器可读错误码与中文消息。"""

    def __init__(self, code: str, message: str, detail: object | None = None) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)

    @property
    def status_code(self) -> int:
        return STATUS_BY_CODE.get(self.code, 400)


def error_payload(request: Request, code: str, message: str, detail: object | None = None) -> dict:
    """构造统一错误响应体。"""
    return {
        "code": code,
        "message": message,
        "detail": detail,
        "request_id": getattr(request.state, "request_id", None),
    }


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。"""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:  # noqa: D401
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(request, exc.code, exc.message, exc.detail),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "BAD_REQUEST"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(request, code, str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_payload(
                request, "VALIDATION_ERROR", "请求参数校验失败", exc.errors()
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常", path=str(request.url.path))
        return JSONResponse(
            status_code=500,
            content=error_payload(request, "INTERNAL_ERROR", "服务器内部错误"),
        )
