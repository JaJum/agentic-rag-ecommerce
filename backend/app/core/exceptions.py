"""
业务异常与全局错误处理：
统一响应结构 {code, message}，避免把堆栈暴露给前端。
"""
from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

log = get_logger(__name__)


class BizError(Exception):
    """业务异常基类：携带错误码与 HTTP 状态码"""

    def __init__(self, message: str, code: str = "BIZ_ERROR", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class AuthError(BizError):
    """认证/鉴权失败（401/403）"""

    def __init__(self, message: str = "未登录或登录已过期", code: str = "AUTH_ERROR"):
        super().__init__(message, code=code, status_code=401)


class ForbiddenError(BizError):
    """权限不足（403）"""

    def __init__(self, message: str = "无权访问该资源", code: str = "FORBIDDEN"):
        super().__init__(message, code=code, status_code=403)


async def biz_error_handler(request: Request, exc: BizError) -> JSONResponse:
    """业务异常 → 统一 JSON 响应"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常 → 500（记录堆栈，前端只见友好文案）"""
    log.error("unhandled_error", path=request.url.path, error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务内部错误，请稍后重试"},
    )
