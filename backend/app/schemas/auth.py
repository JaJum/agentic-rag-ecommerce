"""认证相关 Pydantic 模型：请求体校验与响应结构（自动进 Swagger 文档）"""
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """注册请求：用户名 3~32 位（中英文/数字/下划线），密码 6~64 位"""

    username: str = Field(
        ...,
        min_length=3,
        max_length=32,
        pattern=r"^[\w一-龥]+$",
        description="登录名",
    )
    password: str = Field(..., min_length=6, max_length=64, description="密码")


class LoginRequest(BaseModel):
    """登录请求"""

    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=64)


class ChangePasswordRequest(BaseModel):
    """修改密码请求：需提供原密码（需求 5）"""

    old_password: str = Field(..., min_length=6, max_length=64, description="原密码")
    new_password: str = Field(..., min_length=6, max_length=64, description="新密码")


class UserOut(BaseModel):
    """用户信息出参（不暴露密码哈希）"""

    id: int
    username: str
    role: str

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """登录成功响应：JWT + 用户信息"""

    access_token: str
    token_type: str = "bearer"
    user: UserOut
