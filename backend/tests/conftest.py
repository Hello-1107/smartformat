"""pytest 配置：使用临时 SQLite，测试前后重建表。

注意：环境变量必须在导入 app 之前设置（settings 有 lru_cache）。
SQLite URL 用正斜杠，避免 Windows 反斜杠被误解析。
"""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="sfmt-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(Path(_TMP) / 'test.db').as_posix()}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["STORAGE_DIR"] = str(_TMP / "uploads")

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def reset_db() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth(client):
    """注册并登录一个用户，返回 (headers, user_id)。"""
    resp = client.post(
        "/api/auth/register",
        json={"username": "tester", "password": "secret123", "confirm_password": "secret123"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    user_id = resp.json()["user"]["id"]
    return {"Authorization": f"Bearer {token}"}, user_id


@pytest.fixture
def workspace(client, auth):
    """创建一个工作区，返回 workspace_id。"""
    headers, _ = auth
    resp = client.post("/api/workspaces", json={"name": "测试工作区"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]
