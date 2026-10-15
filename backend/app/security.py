"""密码哈希与 JWT 工具（仅依赖标准库）。

- 密码：PBKDF2-HMAC-SHA256 + 随机盐。
- JWT：HS256，手写 base64url(header).base64url(payload).base64url(HMAC-SHA256)。
  不引入 PyJWT，减少部署依赖；只支持 HS256（与 settings.algorithm 一致）。
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.config import settings


class TokenError(Exception):
    """JWT 校验失败（格式错误 / 签名无效 / 已过期）。"""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000
    ).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        _algo, salt, digest = hashed.split("$", 2)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000
        ).hex()
        return secrets.compare_digest(candidate, digest)
    except (ValueError, AttributeError):
        return False


def _sign(signing_input: bytes) -> bytes:
    return hmac.new(
        settings.secret_key.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + settings.access_token_expire_minutes * 60,
    }
    if extra:
        payload.update(extra)
    segments = [
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    segments.append(_b64url_encode(_sign(signing_input)))
    return ".".join(segments)


def decode_access_token(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("token 格式错误")
    header_b64, payload_b64, signature_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    try:
        expected = _sign(signing_input)
        provided = _b64url_decode(signature_b64)
    except (ValueError, TypeError) as exc:
        raise TokenError("token 解码失败") from exc
    if not hmac.compare_digest(provided, expected):
        raise TokenError("签名无效")
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError) as exc:
        raise TokenError("payload 解析失败") from exc
    exp = payload.get("exp")
    if exp is not None and int(exp) < int(time.time()):
        raise TokenError("token 已过期")
    return payload
