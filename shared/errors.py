"""跨模块应用异常与契约错误辅助。

`AppError` 是业务错误的唯一基类：携带机器可读 `code`、中文 `message`、可选
`detail` 与显式 HTTP 状态码。M1 的 FastAPI 异常处理器负责把它渲染成统一错误结构
（contracts/api-extensions.md），其他模块只抛出本模块提供的辅助函数，不依赖 Web 框架。
"""

from __future__ import annotations

# 业务错误码到 HTTP 状态的映射（契约 1.2）
STATUS_BY_CODE: dict[str, int] = {
    "NOT_FOUND": 404,
    "VALIDATION_ERROR": 422,
    "CONFLICT": 409,
    "FORBIDDEN": 403,
    "UNAUTHORIZED": 401,
    "BAD_REQUEST": 400,
    "SERVICE_UNAVAILABLE": 503,
    "INTERNAL_ERROR": 500,
}


class AppError(Exception):
    """业务异常：携带机器可读错误码、中文消息与可选细节。"""

    def __init__(
        self,
        code: str,
        message: str,
        detail: object | None = None,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        self._status_code = status_code
        super().__init__(message)

    @property
    def status_code(self) -> int:
        if self._status_code is not None:
            return self._status_code
        return STATUS_BY_CODE.get(self.code, 400)


def not_found(code: str, message: str, detail: object | None = None) -> AppError:
    """构造 404 业务异常（SESSION/ATTACKER/ALERT/RULE_NOT_FOUND）。"""
    return AppError(code, message, detail, status_code=404)


def unprocessable(
    code: str = "VALIDATION_ERROR",
    message: str = "请求参数校验失败",
    detail: object | None = None,
) -> AppError:
    """构造 422 业务异常（VALIDATION_ERROR/SORT_FIELD_INVALID/TIME_RANGE_INVALID 等）。"""
    return AppError(code, message, detail, status_code=422)


def conflict(code: str, message: str, detail: object | None = None) -> AppError:
    """构造 409 业务异常（RULE_VERSION_CONFLICT 等）。"""
    return AppError(code, message, detail, status_code=409)


def bad_request(code: str = "BAD_REQUEST", message: str = "请求不合法", detail: object | None = None) -> AppError:
    """构造 400 业务异常。"""
    return AppError(code, message, detail, status_code=400)
