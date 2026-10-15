"""认证相关 schema：账号 + 密码。

- 登录用「账号 + 密码」。
- 注册额外提交 confirm_password，两次密码必须一致（一致性核验）。
- 账号用正则自校验，不引入第三方校验库，减少部署依赖。
"""

import re

from pydantic import BaseModel, Field, field_validator, model_validator

# 账号：3-20 位字母、数字、下划线或中文
# 账号：2-20 位字母、数字、下划线或中文（兼容「张三」这类两字中文名）
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{2,20}$")


def _check_username(value: str) -> str:
    value = value.strip()
    if not _USERNAME_RE.match(value):
        raise ValueError("账号需为 2-20 位字母、数字、下划线或中文")
    return value


class RegisterRequest(BaseModel):
    """注册请求：账号 + 密码 + 确认密码。"""

    # 账号/密码的长度都交给自定义校验器，保证报错口径统一为中文
    username: str = Field(max_length=50)
    password: str = Field(max_length=128)
    confirm_password: str = Field(max_length=128)

    @field_validator("username")
    @classmethod
    def _validate_username(cls, v: str) -> str:
        return _check_username(v)

    @field_validator("password", "confirm_password")
    @classmethod
    def _check_password_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("密码至少 6 位")
        return v

    @model_validator(mode="after")
    def _check_password_consistency(self) -> "RegisterRequest":
        """密码一致性核验：两次输入不一致直接拒绝（422）。"""
        if self.password != self.confirm_password:
            raise ValueError("两次输入的密码不一致")
        return self


class LoginRequest(BaseModel):
    """登录请求：账号 + 密码。

    这里不校验账号/密码格式与长度：任何不合法的输入都统一由
    凭证校验返回 401，避免通过错误码区分「账号是否存在」。
    """

    username: str = Field(max_length=50)
    password: str = Field(max_length=128)

    @field_validator("username")
    @classmethod
    def _strip_username(cls, v: str) -> str:
        """容忍两端空格（用户从别处复制账号时常见）。"""
        return v.strip()


class UserOut(BaseModel):
    id: int
    username: str

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
