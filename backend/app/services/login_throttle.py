"""单进程演示服务的有界登录限流；每个来源与账号独立计数。"""
from collections import OrderedDict
from threading import Lock
from time import monotonic
import hashlib
from fastapi import HTTPException

_attempts = OrderedDict()
_lock = Lock()


def key(address: str, username: str) -> str:
    return hashlib.sha256((address + ':' + username.casefold()).encode()).hexdigest()


def check(bucket: str) -> None:
    now = monotonic()
    with _lock:
        attempts = [t for t in _attempts.get(bucket, []) if now - t < 60]
        if len(attempts) >= 8:
            raise HTTPException(429, "登录失败次数过多，请一分钟后重试", headers={"Retry-After": "60"})


def record(bucket: str, success: bool) -> None:
    now = monotonic()
    with _lock:
        if success:
            _attempts.pop(bucket, None)
        else:
            _attempts[bucket] = [t for t in _attempts.get(bucket, []) if now - t < 60] + [now]
            _attempts.move_to_end(bucket)
        while len(_attempts) > 10000:
            _attempts.popitem(last=False)
